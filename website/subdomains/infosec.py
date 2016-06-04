from flask import Blueprint, render_template

__all__ = ['infosec']

infosec = Blueprint('infosec', __name__, subdomain='infosec')


@infosec.route('/')
def index():
    return render_template('infosec/index.html')


@infosec.route('/demo')
def demo():
    return 'infosec/demo page'
