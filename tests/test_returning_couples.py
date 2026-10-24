from test_app import app,login,csrf,database


def test_first_visit_is_public_but_returning_cookie_only_changes_navigation(app):
    c=app.test_client()
    assert c.get('/').status_code==200
    c.set_cookie('ivory_returning_couple','1')
    assert c.get('/').headers['Location']=='/login'
    assert c.get('/app').headers['Location']=='/login'
    assert c.get('/api/state').status_code==401
    assert c.get('/?welcome=1').status_code==200


def test_successful_login_marks_device_and_expiry_returns_to_login(app):
    c=login(app)
    marker=c.get_cookie('ivory_returning_couple')
    assert marker and marker.value=='1' and marker.http_only and marker.same_site=='Lax'
    assert c.get('/').headers['Location']=='/app'
    assert c.get('/login').headers['Location']=='/app'
    html=c.get('/app').get_data(as_text=True)
    assert 'class="brand" href="/app"' in html
    assert '<a href="/app">Home</a>' in html
    db=database(app);db.execute('UPDATE sessions SET expires=0 WHERE user_id="u1"');db.commit();db.close()
    assert c.get('/app').headers['Location']=='/login'
    assert c.get('/').headers['Location']=='/login'
    page=c.get('/login').get_data(as_text=True)
    assert 'Welcome back' in page and 'carry on with your wedding plans' in page
    assert 'Start your trial' not in page
    assert c.get('/api/state').status_code==401


def test_existing_signed_in_couple_receives_marker_on_next_visit(app):
    c=login(app);c.delete_cookie('ivory_returning_couple')
    assert c.get('/app').status_code==200
    assert c.get_cookie('ivory_returning_couple').value=='1'


def test_couple_logout_opens_signin_and_keeps_public_information_available(app):
    c=login(app)
    result=c.post('/logout',data={'csrf':csrf(c,'/app')})
    assert result.headers['Location']=='/login'
    assert c.get('/api/state').status_code==401
    assert c.get('/').headers['Location']=='/login'
    assert c.get('/?welcome=1').status_code==200


def test_admin_logout_keeps_admin_signin_separate(app):
    c=login(app,'mark@example.com',admin=True)
    assert c.get_cookie('ivory_returning_couple') is None
    response=c.post('/logout',data={'csrf':csrf(c,'/ivoryadmin')})
    assert response.headers['Location']=='/ivoryadmin/login'
    assert c.get('/api/admin/overview').status_code in (401,404)


def test_failed_login_does_not_mark_new_device(app):
    c=app.test_client()
    response=c.post('/login',data={'csrf':csrf(c),'email':'one@example.com','password':'incorrect'})
    assert response.status_code==401
    assert c.get_cookie('ivory_returning_couple') is None
