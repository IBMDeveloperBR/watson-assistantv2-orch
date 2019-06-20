#!/usr/bin/env python

from config import Config
from flask import Flask, render_template, request, jsonify
import atexit, os, sys, ssl, os.path, json

from ibm_watson import AssistantV2
from datetime import datetime as dt
from datetime import timedelta
from urllib.parse import urlparse
import redis

### Setup the Flask WebApp
app = Flask(__name__)
app.config.from_object(Config)

### Read the Watson Assistant credentials from the `wa-credentials.json` file.
with open('wa-credentials.json') as json_file:
    wa_cred = json.load(json_file)
### Authenticate with the AssistantV2 API - SDK will manage the IAM Token.
wa = AssistantV2(version='2019-02-28',
                 iam_apikey=wa_cred['apikey'],
                 url=wa_cred['url'])

### Read the Redis credentials from the `db-credentials.json` file.
with open('db-credentials.json') as json_file:
    db_cred = json.load(json_file)['connection']['rediss']
    connection_string = db_cred['composed'][0]
    parsed = urlparse(connection_string)
    #crt = db_cred['certificate']['certificate_base64']
    #key = db_cred['certificate']['name']
    #print("\nhostname={}".format(parsed.hostname))
    #print("\nport={}".format(parsed.port))
    #print("\npassword={}".format(parsed.password))
### Authenticate and connect to the Redis database.
r = redis.StrictRedis(host=parsed.hostname,
                      port=parsed.port,
                      password=parsed.password,
                      ssl=True,
                      ssl_ca_certs='rediscert.pem',
                      decode_responses=True)

# On IBM Cloud Cloud Foundry, get the port number from the environment variable
# PORT. When running this app on the local machine, default the port to 8000
PORT = int(os.getenv('VCAP_APP_PORT', 8000))
#port = int(os.getenv('PORT', 8000))

'''
*   Watson Assistant V2 API PyFlask Orchestrator Routes
*
'''

@app.route('/parse_input')
def parse_input():
    # Use the session_id specified
    if 'session_id' in request.args:
        session_id = request.args['session_id']
        response = { "Hello" }

    # If no session_id is explicit, check for the fb_user_id parameter
    elif 'fb_user_id' in request.args:
        # Check if there is a registered wa_session for the defined fb_user_id
        session_id_dt = r.get(str(request.args['fb_user_id']))
        if session_id_dt == None:
            # Generate a new session_id if none is present
            session_id = wa.create_session(assistant_id=wa_cred['assistant_id']
                                           ).get_result()['session_id']
            # Save the session_id at Redis
            r.set(str(request.args['fb_user_id']),
                  "{}${}".format(session_id, dt.now().strftime("%c")))
        else:
            # Check if the present session_id is expired
            session_id_dt = session_id_dt.split('$') #Thu Jun 20 04:00:11 2019
            date_time_str = session_id_dt[1]
            date_time_obj = dt.strptime(date_time_str, '%a %b %d %H:%M:%S %Y')
            if (dt.now()-date_time_obj > timedelta(minutes=5)):
                # Generate a new session_id if the present one is expired
                session_id = wa.create_session(assistant_id=wa_cred['assistant_id']
                                               ).get_result()['session_id']
                # Save the session_id at Redis
                r.set(str(request.args['fb_user_id']),
                      "{}${}".format(session_id, dt.now().strftime("%c")))
            else:
                session_id = session_id_dt[0]
        ### Send user input to Watson Assistant
        if 'msg' in request.args:
            usr_input = request.args['msg']
            response = wa.message(assistant_id=wa_cred['assistant_id'],
                                  session_id=session_id,
                                  input={'message_type': 'text',
                                         'text': usr_input}).get_result()
        else:
            response = "Null"
            #ignore call

    # If no session_id nor fb_user_id is specified, create a new session
    else:
        session_id = wa.create_session(assistant_id=wa_cred['assistant_id']
                                       ).get_result()['session_id']
        response = { "Hello" }

    return json.dumps(response) #render_template('index.html', resp=response)

''' Example Response
{
  "messages": [
    {
      "text": "Não entendi. Pode repetir?"
    }
  ]
}
'''

''' Current Response
{
  "output": {
    "generic": [
      {
        "response_type": "text",
        "text": "Não entendi. Pode repetir?"
      }
    ],
    "intents": [],
    "entities": []
  }
}
'''
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
