"""Integration checks for presentation assets and the existing couple workflows."""
import io
from PIL import Image
from test_app import app, login, publish


def test_glass_assets_are_public_local_and_compact(app):
    client = app.test_client()
    css = client.get('/static/glass.css')
    image = client.get('/static/botanical-background.webp')
    assert css.status_code == image.status_code == 200
    assert css.mimetype == 'text/css'
    assert image.mimetype == 'image/webp'
    assert len(image.data) < 100_000
    with Image.open(io.BytesIO(image.data)) as background:
        assert background.height > background.width >= 900
    assert 'https://' not in css.get_data(as_text=True)


def test_couple_tools_load_theme_without_mutating_shared_plan(app):
    client = login(app)
    original = client.get('/api/state').json
    for route in ('/app', '/hub', '/files', '/website', '/upgrade'):
        response = client.get(route)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert html.index('/static/style.css') < html.index('/static/couple.css') < html.index('/static/glass.css')
        assert 'id="couple-dock"' in html
        assert 'id="planner-install"' in html
    assert client.get('/api/state').json == original


def test_admin_and_auth_share_finish_keep_authentication_boundaries(app):
    client = app.test_client()
    for route in ('/', '/login', '/recover', '/ivoryadmin/login'):
        response = client.get(route)
        assert response.status_code == 200
        assert '/static/glass.css' in response.get_data(as_text=True)
    assert client.get('/ivoryadmin').status_code == 302
    admin = login(app, email='mark@example.com', admin=True)
    html = admin.get('/ivoryadmin').get_data(as_text=True)
    assert html.index('/static/admin.css') < html.index('/static/glass.css')
    assert 'admin-app' in html and 'id="sa-main"' in html


def test_couple_chosen_wedding_website_theme_is_preserved(app):
    client = login(app)
    publish(client)
    response = app.test_client().get('/weddings/emma-and-jamie')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'theme-garden' in html
    assert '/static/glass.css' not in html
    assert 'Reply to your invitation' in html
