
from flask import Flask
from flask import request
import os
import requests
import json
import time
import paramiko
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

app = Flask(__name__)

STATUS_API_URL = "http://34.201.215.104/api/v1"
STATUS_API_TOKEN = "EEgPtRLSknFb4uesTD5M"
STATUS_PAGE_URL = "http://34.201.215.104"

@app.route('/hello', methods=['POST'])
def hello():
    message = "Hello"
    return send_message_to_slack(message)

@app.route('/events', methods=['POST'])
def events():
    sensu_api_url = "http://35.153.71.96:8080/api/core/v2/namespaces/default/events"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Key 6b8e1f52-ffcc-472b-a4eb-4e1632980fdb"
    }
    response = requests.get(sensu_api_url, headers=headers)
    print(response.status_code)
    return (response.text)

@app.route('/resolve', methods=['POST'])
def resolve():
    try:
        entity, check = request.values.get('text').split()
    except ValueError:
        return f"Invalid command format. Use: /resolve-alert <entity> <check>"
    sensu_api_url = f"http://35.153.71.96:8080/api/core/v2/namespaces/default/events/{entity}/{check}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Key 6b8e1f52-ffcc-472b-a4eb-4e1632980fdb"
    }
    data = {
            "entity": {
                "metadata": {
                    "name": entity,
                    "namespace": "default"
                 }
            },
            "check": {
                "output": "Resolved from api",
                "handlers": ["slack"],
                "status" : 0,
                "subscriptions": ["system"],
            }
    }
    # Make the API request to resolve the event
    response = requests.put(sensu_api_url, headers=headers, json=data)
    print(response.status_code)
    # Check the response and respond to the Slack command
    if response.status_code == 200 or response.status_code == 201:
        slack_message = f"Event {check} for entity {entity} has been resolved successfully."
        return send_resolve_message_to_slack(slack_message,entity,check)
    else:
        return(f"Failed to resolve event. Status code: {response.status_code}, Response: {response.text}")


@app.route('/create-incident', methods=['POST'])
def create_incident():
    try:
        name, description = request.values.get('text').split(", ")
    except ValueError:
        return f"Invalid command format. Use: /create-incident <name>, <description>"

    incident_data = {
        "name": name,
        "message": description,
        "status": 1,  # 1 for 'Investigating'
        "visible": True  # Optional: set to False if you don't want it public
    }

    headers = {
        'X-Cachet-Token': STATUS_API_TOKEN,
        'Content-Type': 'application/json'
    }

    response = requests.post(STATUS_API_URL+"/incidents", json=incident_data, headers=headers)

    if response.status_code == 200 or response.status_code == 201:
        print('Incident created successfully', response.json())
        data = response.json()['data']
        link = data['permalink']
        return send_message_to_slack('Incident created successfully - '+ link)
    else:
        print('Failed to create incident:', response.status_code, response.text)
        error_msg = "Failed to create incident: "+ response.text
        return send_message_to_slack(error_msg)

@app.route('/update-incident', methods=['POST'])
def update_incident():
    try:
        update_type, update_message = request.values.get('text').split(", ")
    except ValueError:
        return f"Invalid command format. Use: /update-incident <type>, <message>"
    status = 1
    update_type = update_type.lower()
    if update_type == 'identified':
        status = 2
    elif update_type == 'watching':
        status = 3
    elif update_type == 'fixed':
        status = 4
    else:
        return send_message_to_slack("Invalid entry for update type, Valid entries are Identified/Watching/Fixed")


    data = {
        "message": update_message,
        "status": status
    }
    headers = {
        'X-Cachet-Token': STATUS_API_TOKEN,
        'Content-Type': 'application/json'
    }
    id = None
    get_incident_response = requests.get(STATUS_API_URL+"/incidents", headers=headers)
    if get_incident_response.status_code == 200:
        incidents = get_incident_response.json().get('data', [])
        if incidents:
            latest_incident = incidents[-1]
            id = latest_incident['id']
            print(id)

    if id:
        url = (STATUS_API_URL+'/incidents/{id}/updates').format(id=id)
        response = requests.post(url, json=data,headers=headers)
        if response.status_code in [200,201]:
            incident_url = (STATUS_PAGE_URL+'/incidents/{id}').format(id=id)
            return send_message_to_slack("Incident update posted successfully. Incident link - "+ incident_url)
        else:
            return send_message_to_slack("Failed to post incident update")

    
@app.route('/list-incidents', methods=['POST'])
def list_incidents():
    headers = {
        'X-Cachet-Token': STATUS_API_TOKEN,
        'Content-Type': 'application/json'
    }
    
    response = requests.get(STATUS_API_URL+"/incidents", headers=headers)
    if response.status_code == 200:
        incidents = response.json().get('data', [])
        slack_message_json = {
            "response_type": "in_channel",
            "blocks": [
                {
                    "text": {
                        "text": "Incidents",
                        "type": "plain_text"
                    },
                    "type": "header"
                },
                {
                    "fields": [
                        {
                            "text": "*Incident*",
                            "type": "mrkdwn"
                        },
                        {
                            "text": "*Status*",
                            "type": "mrkdwn"
                        }
                    ],
                    "type": "section"
                }
            ]
        }
        for incident in incidents:
            slack_message_json["blocks"].append({"type": "divider"})
            body_to_add = {
                "fields":[
                    {
                        "text": "<"+incident['permalink']+"|"+ incident['name'] +">",
                        "type": "mrkdwn"
                    },
                    {
                        "text": incident['latest_human_status'],
                        "type": "mrkdwn"
                    }
                ],
                "type": "section"
            }
            slack_message_json['blocks'].append(body_to_add)
        return slack_message_json
        
@app.route('/delete-incident', methods=['POST'])
def delete_incident():
    try:
        id = request.values.get('text').split()[0]
    except Exception as e:
        print(e)
        return f"Invalid command format. use /delete-incident <id>"
    headers = {
        'X-Cachet-Token': STATUS_API_TOKEN,
        'Content-Type': 'application/json'
    }
            
    if id:
        url = f"{STATUS_API_URL}/incidents/{id}"
        response = requests.delete(url, headers=headers)
        if response.status_code in [200, 204]:
            return send_message_to_slack("Incident deleted successfully")
        else:
            return send_message_to_slack("Failed to delete incident")

        
@app.route('/help', methods=['POST'])
def help():
    
    slack_response = {
        "response_type": "in_channel",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Please refer below to see how to use the commnands: "
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*/resolve*\nThis command is to resolve incoming sensu alert.\n*Run: /resolve <entity> <check> *\n\nGet \"entity\" and \"check\" parameters from the alert.\n*Both paramaters are mandatory.* "
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*/list-incidents*\nThis command is to list the incidents from the status page.\n*Run: /list-incidents*\n"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*/create-incident*\nThis command is to create new incident in the status page.\n*Run: /create-incident <name> <description>*\n\n Enter \"name\" and \"description\" parameters of your choice.\n*Both paramaters are mandatory.* "
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*/update-incident*\nThis command is to update status of incidents in the status page.\n*Run: /update-incident <type> <message>*\n\n\"type\" can have one of the following values:\n*identified, watching, fixed*\n \"message\" can be of your choice.\n*Both paramaters are mandatory.* "
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*/delete-incident*\nThis command is to delete an incident from the status page.\n*Run: /delete-incident <id>*\n\nTo get \"id\", first list the incidents using /list-incidents command and take the last digit from the link of the incident to be deleted.  "
                }
            },
            {
                "type": "divider"
            }
        ]
    }
    return slack_response

@app.route('/check-service', methods=['POST'])
def check_service():
    try:
        service_name, hostname = request.values.get('text').split()
    except Exception as e:
        print(e)
        return f"Invalid command format. use /check-service <service> <hostname>"
    user = 'slackuser'
    password = 'slack@123'

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=user, password=password)
        stdin, stdout, stderr = ssh.exec_command(f'systemctl is-active {service_name}')
        service_status = stdout.read().decode().strip()
        response_text = f"The status of {service_name} on {hostname} is {service_status}"
    except Exception as e:
        response_text = f"Failed to check the status of {service_name} on {hostname}: {str(e)}"
    finally:
        ssh.close()

    try:
        return send_message_to_slack(response_text)
    except Exception as e:
        print(e)

@app.route('/start-service', methods=['POST'])
def start_service():
    try:
        service_name, hostname = request.values.get('text').split()
    except Exception as e:
        print(e)
        return f"Invalid command format. use /start-service <service> <hostname>"
    user = 'slackuser'
    password = 'slack@123'

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=user, password=password)
        stdin, stdout, stderr = ssh.exec_command(f'echo {password} | sudo -S sudo systemctl start {service_name}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status == 0:
            response_text = f"Service {service_name} started successfully! "
        else:
            response_text = f"Failed to start service {service_name}. Error: {stderr.read().decode()}"
    except Exception as e:
        response_text = f"Failed to start {service_name} on {hostname}: {str(e)}"
    finally:
        ssh.close()

    try:
        return send_message_to_slack(response_text)
    except Exception as e:
        print(e)

@app.route('/stop-service', methods=['POST'])
def stop_service():
    try:
        service_name, hostname = request.values.get('text').split()
    except Exception as e:
        print(e)
        return f"Invalid command format. use /start-service <service> <hostname>"
    user = 'slackuser'
    password = 'slack@123'

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=user, password=password)
        stdin, stdout, stderr = ssh.exec_command(f'echo {password} | sudo -S systemctl stop {service_name}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status == 0:
            response_text = f"Service {service_name} stopped successfully! "
        else:
            response_text = f"Failed to stop service {service_name}. Error: {stderr.read().decode()}"
    except Exception as e:
        response_text = f"Failed to stop {service_name} on {hostname}: {str(e)}"
    finally:
        ssh.close()

    try:
        return send_message_to_slack(response_text)
    except Exception as e:
        print(e)
    
def send_resolve_message_to_slack(message,entity,check):
    block_kit_message = {
        "response_type": "in_channel",
        "blocks": [
          {
            "type": "section",
            "text": {
              "type": "mrkdwn",
              "text": "*Description*\nResolved by bot\n"+message+"\n"
            },
            "fields": [
            {
              "type": "mrkdwn",
              "text": "*Status*"
            },
            {
              "type": "mrkdwn",
              "text": "\n\n"
            },
            {
              "type": "plain_text",
              "text": "Resolved\n"
            },
            {
              "type": "plain_text",
              "text": "\n"
            },
            {
              "type": "mrkdwn",
              "text": "*Entity*"
            },
            {
              "type": "mrkdwn",
              "text": "*Check*"
            },
            {
              "type": "plain_text",
              "text": entity
            },
            {
              "type": "plain_text",
              "text": check
            }
          ]
        }
      ]
    }
    return block_kit_message

def send_message_to_slack(message):
    block_kit_message = {
        "response_type": "in_channel",
        "blocks": [
		    {
			    "type": "section",
			    "text": {
				    "type": "mrkdwn",
				    "text": message
			    }
		    }
	    ]
    }
    return block_kit_message

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
