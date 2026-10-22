import io
import json
from PIL import Image
from test_app import app, login


def test_home_screen_assets_public_and_start_at_sign_in_gate(app):
    client = app.test_client()
    response = client.get('/static/planner.webmanifest')
    assert response.status_code == 200
    assert response.mimetype == 'application/manifest+json'
    data = json.loads(response.data)
    assert data['start_url'] == '/app'
    assert data['display'] == 'standalone'
    assert data['scope'] == '/'
    assert 'Set-Cookie' not in response.headers
    assert client.get('/app').status_code == 302
    for icon in data['icons']:
        image = client.get(icon['src'])
        assert image.status_code == 200
        with Image.open(io.BytesIO(image.data)) as png:
            assert f'{png.width}x{png.height}' == icon['sizes']
    assert 'email' not in response.get_data(as_text=True)


def test_couple_has_prompt_and_reopen_control_on_all_couple_tools(app):
    client = login(app)
    for path in ('/app', '/hub', '/files', '/website', '/upgrade'):
        html = client.get(path).get_data(as_text=True)
        assert 'id="planner-install"' in html
        assert 'data-install-open' in html
        assert '/static/planner-install.js' in html
        assert 'rel="manifest"' in html


def test_public_and_admin_login_do_not_get_couple_install_prompt(app):
    client = app.test_client()
    for path in ('/', '/login', '/ivoryadmin/login'):
        html = client.get(path).get_data(as_text=True)
        assert 'id="planner-install"' not in html
        assert '/static/planner-install.js' not in html
