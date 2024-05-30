from random import choice, uniform
from time import sleep
from tqdm import tqdm

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Configure Chrome options for headless browsing
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# Define the number of clicks
instance_count = 200

# Replace with your target URL
query_url = 'http://localhost:8000/query/query_page/query_page/28aee831f2cfb8094b9d2a86bb9a02'

# Replace with number of examples
n = 25
# Create a list to store the WebDriver instances
drivers = []


# Define a function to get random sleep intervals
def random_sleep(min_time=0.2, max_time=1.0):
    sleep(uniform(min_time, max_time))


# Create multiple instances of headless Chrome
print("Loading headless Chrome instances:")
for _ in tqdm(range(instance_count)):
    driver = webdriver.Chrome(options=chrome_options)
    drivers.append(driver)

# Iterate through the drivers and perform the clicks
print("\nLoading experiment query pages:")
for driver in tqdm(drivers):
    driver.get(query_url)

print(f"\nSimulating {n} users conducting the experiment:")
for i in tqdm(range(n)):
    for driver in drivers:
        # Wait until the elements with div ids 'left' and 'right' are clickable
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, 'left')))
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, 'right')))

        # Randomly select either 'left' or 'right' element ID for each click
        element_id = choice(['left', 'right'])
        driver.find_element(By.ID, element_id).click()

        random_sleep()

# Quit all the WebDriver instances
print("\nShutting down the WebDriver instances:")
for driver in tqdm(drivers):
    driver.quit()
