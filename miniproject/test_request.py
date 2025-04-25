import requests

# Sample data for the request
url = 'http://127.0.0.1:5000/get_recommendations'
data = {
    'goal': 'weight loss',
    'level': 'beginner',
    'preferences': 'vegetarian',
    'allergies': '',
    'workout_type': 'strength',
    'workout_split': 'full body',
    'workout_frequency': '3',
    'workout_duration': '30'
}

# Simulate a POST request to the endpoint
response = requests.post(url, data=data)

# Print the response
print("Response Status Code:", response.status_code)
print("Response JSON:", response.json())
