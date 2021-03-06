import os
import json
import collections
from itertools import filterfalse, tee
from operator import attrgetter

import flask
import requests
from werkzeug.contrib.cache import SimpleCache

from . import server_config
from .utils import invite, database, views
from .models.posts import Post
from . import app

cache = SimpleCache()

User = collections.namedtuple('User', 'username skills points last_seen')


@app.route('/')
@app.route('/index')
def index():
    articles = Post.query.all()
    return flask.render_template('index.html', articles=reversed(articles))


@app.route('/docs')
def docs():
    return flask.render_template('docs.html')


@app.route('/about')
def about():
    return flask.render_template('about.html')


@app.route('/resources')
def resources():
    res = cache.get('resources')
    if not res:
        with open(os.path.join(os.path.dirname(__file__), 'database/resources.json')) as f:
            res = json.loads(f.read(), object_pairs_hook=collections.OrderedDict)
        cache.set('resources', res, timeout=1800)  # 30 mins timeout
    return flask.render_template('resources.html', link=res)


@app.route('/members')
def members():
    all_users = json.loads(database.get_all_users())
    if not all_users['ok']:
        flask.abort(500)

    users = [User(username=user['username'], skills=user['skills'], points=user['points'], last_seen='Not Available')
             for user in all_users['response']]

    order = flask.request.args.get('order')
    lang = flask.request.args.get('lang', '').lower()

    if order == 'points':
        users.sort(key=attrgetter('points'), reverse=True)
    else:
        users.sort(key=attrgetter('username'))

    if lang:
        t1, t2 = tee(users)
        lang_yes = filter(lambda user: lang in user.skills.lower(), t1)
        lang_no = filterfalse(lambda user: lang in user.skills.lower(), t2)

        users = list(lang_yes) + list(lang_no)

    return flask.render_template('members.html', members=users)


@app.route('/join', methods=['GET', 'POST'])
def join():
    if flask.request.method == 'POST':
        email = flask.request.form['email']
        skills = flask.request.form['skills']

        # redir: -1, 0 or 1
        # -1: stay on page;    0: redirect to index.html;    1: redirect to slack
        if email == '' or skills == '':
            redir, resp = -1, 'Please fill every field!'
        else:
            redir, resp = invite.send_invite(email.lower(), skills)

        return flask.render_template('join.html', status=redir, rep_error=resp)
    else:
        return flask.render_template('join.html', status=None, rep_error=None)


@app.route('/_database', methods=['GET', 'POST', 'PUT', 'DELETE'])
@views.must_login
def _database():
    args = {var_name: flask.request.args.get(var_name, '').lower()
            for var_name in ('email', 'username', 'slack_id', 'github', 'skills', 'timezone', 'points')}

    if flask.request.method == 'POST':
        return database.insert_user(email=args['email'], username=args['username'], slack_id=args['slack_id'],
                                    skills=args['skills'], github=args['github'], timezone=args['timezone'],
                                    points=args['points'])

    elif flask.request.method == 'PUT':
        params = {key: value for key, value in args.items() if value}

        # slack_id is the primary ID of every user
        # BUT when they sign up on the site, only their email gets stored, so we can't identify them with slack_id
        # so when they sign into slack for the first time, we update their email and slack id values
        if flask.request.args.get('cheat') == 'first_signin':
            return database.update_user(email=args['email'], params=params)
        else:
            return database.update_user(email=args['email'], username=args['username'], slack_id=args['slack_id'],
                                        params=params)

    elif flask.request.method == 'GET':
        if flask.request.args.get('req_all') == 'true':
            return database.get_all_users()
        return database.get_user(email=args['email'], username=args['username'], slack_id=args['slack_id'])

    elif flask.request.method == 'DELETE':
        return database.delete_user(email=args['email'], username=args['username'], slack_id=args['slack_id'])


@app.route('/_login')
def login():
    uri = 'https://github.com/login/oauth/authorize' \
          '?client_id={}'.format(server_config.GIT_CLIENT_ID)
    return flask.redirect(uri, code=302)


@app.route('/_callback')
def auth():
    session_code = flask.request.args.get('code', '')

    if session_code != '':
        resp = requests.post(
            'https://github.com/login/oauth/access_token',
            data={
                'client_id': server_config.GIT_CLIENT_ID,
                'client_secret': server_config.GIT_CLIENT_SECRET,
                'code': session_code
            },
            headers={
                'accept': 'application/json'
            }
        )
        if resp.status_code == 200:
            resp = json.loads(resp.text)
            acc_info = requests.get('https://api.github.com/user',
                                    params={'access_token': resp.get('access_token')})
            if acc_info.status_code == 200:
                acc_info = json.loads(acc_info.text)
                flask.session['username'] = acc_info.get('login')

            return flask.redirect(flask.url_for('index'))

    return 'Something went wrong'


@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def page_not_found(error):
    if str(error).startswith('403'):
        return flask.render_template('errors/403.html'), 403
    elif str(error).startswith('404'):
        return flask.render_template('errors/404.html'), 404
    elif str(error).startswith('500'):
        return flask.render_template('errors/500.html'), 500
