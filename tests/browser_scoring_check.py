"""Check logout, score limits, saved results and empty new-round inputs in Chrome."""
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from playwright.sync_api import sync_playwright


with tempfile.TemporaryDirectory() as tmp:
    app.DB = os.path.join(tmp, 'test.sqlite3')
    server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))

            def state():
                return page.request.get(base + '/api/state').json()['tournament']

            def api(action, **data):
                t = state()
                response = page.request.post(base + '/api/' + action,
                                            data=dict(data, revision=t['revision'] if t else None))
                assert response.ok, response.text()

            def credentials():
                page.locator('[name=login]').fill('scoring-check')
                page.locator('[name=password]').fill('secret123')
                page.locator('#auth button').click()
                page.locator('#create').wait_for()

            page.goto(base)
            page.locator('#toggle').click()
            credentials()
            page.locator('#logout').click()
            page.get_by_role('heading', name='Кіру', exact=True).wait_for()
            credentials()
            page.locator('#create').click()
            page.locator('[name=name]').fill('Балл сынағы')
            page.locator('[name=count]').fill('2')
            page.locator('[name=score_min]').fill('25')
            page.locator('[name=score_max]').fill('25')
            assert not page.locator('#setup').evaluate('(f)=>f.checkValidity()')
            page.locator('[name=score_min]').fill('30')
            assert not page.locator('#setup').evaluate('(f)=>f.checkValidity()')
            page.locator('[name=score_min]').fill('20')
            page.locator('#setup-next').click()
            page.locator('#teams-tab').wait_for()
            assert (state()['score_min'], state()['score_max']) == (20, 25)
            for i in range(2):
                api('team', name=f'T{i}', speaker1='A', speaker2='B')
            api('judge', name='J')
            api('finish_registration')
            api('start')
            t = state()
            rooms = t['rounds'][-1]['rooms']
            rooms[0]['judges'] = [t['judges'][0]['id']]
            api('confirm', number=1, rooms=rooms)
            page.reload()
            page.locator('tr.clickable').click()
            fields = page.locator('#result input[type=number]')
            assert fields.count() == 4
            assert all(v == '' for v in fields.evaluate_all('(xs)=>xs.map(x=>x.value)'))
            page.locator('[name=winner]').select_option(index=1)
            for field in fields.all():
                field.fill('20')
            fields.first.fill('26')
            page.locator('#result button[type=submit], #result button:not([type])').click()
            assert '20–25' in page.locator('#result-error').inner_text()
            assert state()['rounds'][-1]['results'] == {}
            fields.first.fill('25')
            page.locator('#result button:not([type])').click()
            page.wait_for_function('!document.querySelector("dialog").open')
            page.locator('tr.clickable').click()
            assert '25' in page.locator('#result input[type=number]').evaluate_all('(xs)=>xs.map(x=>x.value)')
            page.get_by_role('button', name='Жабу', exact=True).click()
            api('next', number=1)
            t = state()
            rooms = t['rounds'][-1]['rooms']
            rooms[0]['judges'] = [t['judges'][0]['id']]
            api('confirm', number=2, rooms=rooms)
            page.reload()
            page.locator('tr.clickable').click()
            assert all(v == '' for v in page.locator('#result input[type=number]').evaluate_all('(xs)=>xs.map(x=>x.value)'))
            assert page.locator('#result input[type=number]').first.get_attribute('min') == '20'
            assert page.locator('#result input[type=number]').first.get_attribute('max') == '25'
            page.set_viewport_size(dict(width=390, height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors, errors
            browser.close()
            print('PASS: logout → login, invalid limits, score range, edit saved scores, empty next round, mobile width')
    finally:
        server.shutdown()
        server.server_close()
