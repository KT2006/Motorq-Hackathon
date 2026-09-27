from locust import HttpUser, task, between
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class FleetAPIUser(HttpUser):
    wait_time = between(0.1, 0.5)
    
    def on_start(self):
        """ Fetch a JWT token when a user starts """
        response = self.client.post("/token")
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.headers = {}
    
    @task(3)
    def get_offenders(self):
        """ Simulates fetching the worst offenders on the dashboard """
        self.client.get("/fleet/offenders?limit=10&from_date=2026-08-01&to_date=2026-08-31", headers=self.headers)
        
    @task(1)
    def get_overview(self):
        """ Simulates fetching the fleet overview """
        self.client.get("/fleet/summary?month=2026-08-01", headers=self.headers)
