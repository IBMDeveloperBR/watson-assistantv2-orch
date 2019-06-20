import os

class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY') or '321546yrhbwsf14c41'
