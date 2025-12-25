import json

#-----json Config-----
JSON_CONFIG_FILE = "config.json"

#-----json Variables-----

def readFromJSON(key):
    try:
        with open(JSON_CONFIG_FILE, 'r') as jsonFile:
            data = json.load(jsonFile)
            return data.get(key, None)
    except Exception as e:
        print("Error reading JSON config:", e)
        return None
    
def writeToJSON(key, value):
    try:
        with open(JSON_CONFIG_FILE, 'r') as jsonFile:
            data = json.load(jsonFile)
        
        data[key] = value
        
        with open(JSON_CONFIG_FILE, 'w') as jsonFile:
            json.dump(data, jsonFile)
    except Exception as e:
        print("Error writing to JSON config:", e)