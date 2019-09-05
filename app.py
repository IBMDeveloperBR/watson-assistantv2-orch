import gunicorn_config

from os import urandom
from urllib.parse import urlparse
import redis, base64, json

from datetime import datetime as dt
from datetime import timedelta

from time import sleep
from flask import Flask, render_template, request, jsonify
from flask_sslify import SSLify

from ibm_watson import AssistantV2


'''
    Initial Application Setup
    - A random SECRET_KEY is generated;
    - SSLify is used to handle SSL certification.
'''
# Start Flask Application:
app = Flask(__name__)
# Configure a random SECRET_KEY:
app.config['SECRET_KEY'] = urandom(16)
# Setup SSLify for HTTPS communication:
# sslify = SSLify(app)


'''
    IBM Cloud Services Authentication
    - A Redis instance is used to handle WA sessions;
    - Watson Assistant uses the V2 API.
'''
# Read Watson Assistant credentials from the `wa-credentials.json` file:
WA_JSONFILE = "wa_credentials.json"
with open(WA_JSONFILE) as json_file:
    wa_cred = json.load(json_file)
# Authenticate with the AssistantV2 API,
# The Watson SDK will manage the IAM Token:
wa = AssistantV2(version='2019-02-28',
                 iam_apikey=wa_cred['apikey'],
                 url=wa_cred['url'])
# Read Redis credentials from the `iredis-credentials.json` file:
REDIS_JSONFILE = "iredis_credentials.json"
with open(REDIS_JSONFILE) as json_file:
    iredis_cred = json.load(json_file)['connection']['rediss']
connection_string = iredis_cred['composed'][0]
parsed = urlparse(connection_string)
# Build the Redis root certificate .pem file:
with open("rediscert.pem", "w") as rootcert:
    coded_cert = iredis_cred['certificate']['certificate_base64']
    rootcert.write(base64.b64decode(coded_cert).decode('utf-8'))

'''
    Establish connection with Redis
'''
print("\nConnecting to IBM Cloud Redis...")
try:
    # The decode_responses flag here directs the client,
    # to convert the responses from Redis into Python 
    # strings using the default encoding utf-8.
    iredis = redis.StrictRedis(
        host=parsed.hostname,
        port=parsed.port,
        password=parsed.password,
        ssl=True,
        ssl_ca_certs='rediscert.pem',
        decode_responses=True
    )
    print("\nConnected successfully to IBM Cloud Redis.")
except Exception as error:
    print("\nException: {}".format(error))
finally:
    pass


'''
    Flask Watson Assistant V2 Orchestrator Chatfuel Route
    - The `chatfuel` route is an API to be integrated with the Chatfuel service;
    - The chatfuel service is a convenient method for fast integration with Facebook.
'''
@app.route('/chatfuel') #args: fb_user_id & msg
def chatfuel():
    '''
        Retrieve, or set a new, Watson Assistant `session_id`.
    '''
    # Check Redis for `session_id` based on the `fb_user_id`:
    session_id_dt = iredis.get(str(request.args['fb_user_id']))
    if session_id_dt == None:
        # Generate a new session_id if none is present
        session_id = wa.create_session(assistant_id=wa_cred['assistant_id']
                                       ).get_result()['session_id']
        # Save the session_id at Redis
        iredis.set(str(request.args['fb_user_id']),
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
            # Save the new session_id at Redis
            iredis.set(str(request.args['fb_user_id']),
                  "{}${}".format(session_id, dt.now().strftime("%c")))
        else:
            # Session at Redis is still active
            session_id = session_id_dt[0]

    '''
        Send user input to Watson Assistant
    '''
    usr_input = request.args['msg']
    response = wa.message(assistant_id=wa_cred['assistant_id'],
                          session_id=session_id,
                          input={'message_type': 'text', 'text': usr_input}
                         ).get_result()

    ### Parse Watson Assistant response
    messages = []
    for i in response['output']['generic']:
        # Currently, only text type messages are supported
        if i['response_type'] == 'text':
            messages.append(dict(text=i['text']))
        else:
            messages.append(dict(text="Watson Assistant is Unavailable"))
        '''
        elif i['response_type'] == 'image':
            messages.append(dict(attachment=dict(type='image',
                            payload=dict(url=i['source']))))
        elif i['response_type'] == 'option':
            buttons = []
            for b in range(i['options']['lenght']-1):
                buttons.append(dict(type='show_block',
                                block_names=['Options'],
                                title=i['options'][b]['label']))
                messages.append(dict(attachment=dict(type='template',
                                payload=dict(template_type='button',
                                text=i['options']['title'], buttons=buttons))))
        '''


    '''
        Build and return the response structure
        - Chatfuel Example Response
            {
                "messages": [
                    {
                    "text": "Não entendi. Pode repetir?"
                    }
                ]
            }
        - Standard Watson Assistant JSON Response
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
    response = dict(messages=messages)
    return json.dumps(response)


'''
    Route for clearing completely the Redis database
    - Should be called periodically for maintenance.
'''
@app.route('/clean_redis')
def clean_redis():
    try:
        # The decode_responses flag here directs the client,
        # to convert the responses from Redis into Python 
        # strings using the default encoding utf-8.
        iredis2 = redis.StrictRedis(
            host=parsed.hostname,
            port=parsed.port,
            password=parsed.password,
            ssl=True,
            ssl_ca_certs='rediscert.pem',
            decode_responses=True
        )
        print("\nConnected successfully to IBM Cloud Redis.")
    except Exception as error:
        return "\nException: {}".format(error)
    finally:
        # Start clearing keys
        count = 0
        for key in iredis2.scan_iter():
            count = count + 1
            iredis2.delete(key)
        return "Deleted {} Redis keys.".format(count)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=gunicorn_config.PORT, debug=False)
