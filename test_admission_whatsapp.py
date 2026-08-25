import requests
import json
 
# Replace with the actual recipient's WhatsApp number (with country code, e.g., 918401611072)
RECIPIENT_NUMBER = "918401611072"
PHONE_NUMBER_ID = "1168578376348442"
ACCESS_TOKEN = "EAA3kk7FBaZCIBSfO3yGnrqNyTlURSoReYETRyVZBnvrlcS56S7ZBnJUsCjAQ9wzH8GReo5N31DMCa7H1muvwvZC3l1ZCJoI8nvZCcW6OFrAcK4TAPJyFV9XZAc2LxncfivZAfJt2rqwf4TTzH4CZB5ZC732q93G8qqDPyeR4j5GdqCsuISpLZAJrJjdJOJmhnWiZCYUtB3j3UPwe065l2XmmyHQG2S384a0rzCllI1iTQN3p4mgIVhFjwReO84v63sgzoHFmZBdXLl6DSNAB1b68Nk3AX7ZBdWZASVEuskmm695ayihUtrIMJrvEx7PPV9yyr5yj0JaxB2Q3uMzKCQZD"
 
url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
 
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}
 
data = {
    "messaging_product": "whatsapp",
    "to": RECIPIENT_NUMBER,
    "type": "template",
    "template": {
        "name": "admission_process",
        "language": {
            "code": "en"
        },
        "components": [
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": "Rahul Mehta"
                    },
                    {
                        "type": "text",
                        "text": "Insight Institute of Professional Studies"
                    }
                ]
            },
            {
                "type": "button",
                "sub_type": "url",
                "index": 0,
                "parameters": [
                    {
                        "type": "text",
                        "text": "api/auth/set-password?token=DTFYFYTYTYFRY"
                    }
                ]
            }
        ]
    }
}
 
response = requests.post(url, headers=headers, json=data)
 
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")
 
 
