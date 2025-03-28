from random import choice, uniform
from time import sleep
from tqdm import tqdm

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

import numpy as np
# Configure Chrome options for headless browsing
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
# chrome_options.add_argument('--incognito')


# test instance_count = 100, n = 1000, num_targets_in_query = 25;
# test instance_count = 50, n = 1000, num_targets_in_query = 100;

# test instance_count = 20, n = 100, num_targets_in_query = 10;

# Define the number of simulated users
instance_count = 50 # up to 100

# Replace with your target URL
query_url = 'http://44.223.248.38/query/query_page/query_page/bbea352d484acb2dab7216f5538b91'
n = 1000    # num_tries Up to 1000
# Create two groups for experiment
num_targets_in_query = 100  # Up to 100
# Create two groups 
groups = np.array([0]*(instance_count//2) + [1]*(instance_count//2))
np.random.shuffle(groups)
# Create two choices
seed = 42
rng = np.random.default_rng(seed)
first_group_choices = np.array([rng.permutation(num_targets_in_query) 
                                for _ in range(n)])
second_group_choices = np.array([rng.permutation(num_targets_in_query) 
                                for _ in range(n)])
# Create a list to store the WebDriver instances
drivers = []
# Define a function to get random sleep intervals
def random_sleep(min_time=0.2, max_time=1.0):
    sleep(uniform(min_time, max_time))

REMOTE_WEBDRIVER_URL = 'http://127.0.0.1:4444/wd/hub'  # or your Docker host IP

# Create multiple instances of headless Chrome
print("Loading headless Chrome instances:")
for _ in tqdm(range(instance_count)):
    driver = webdriver.Remote(
        command_executor=REMOTE_WEBDRIVER_URL,
        options=chrome_options
    )
    drivers.append(driver)



# Iterate through the drivers and perform the clicks
print("\nLoading experiment query pages:")
for driver in tqdm(drivers):
    driver.get(query_url)

print(f"\nSimulating {instance_count} users conducting the experiment:")
print(f"\nSimulating {n} queries in the experiment:")


for i in tqdm(range(n)):
    for j, driver in enumerate(drivers):
        # # Wait until the elements with div ids 'left' and 'right' are clickable
        # WebDriverWait(driver, 10).until(
        #     EC.element_to_be_clickable((By.ID, 'left')))
        # WebDriverWait(driver, 10).until(
        #     EC.element_to_be_clickable((By.ID, 'right')))
        
        # # Randomly select either 'left' or 'right' element ID for each click
        # element_id = choice(['left', 'right'])
        # driver.find_element(By.ID, element_id).click()

        # random_sleep()
         # 1) Wait for the main container to appear:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "targets-container"))
        )

        # 2) Gather the clickable targets inside #targets-container
        #    (all <div class="target-container">).
        #    We'll use a short wait to ensure all child divs are present.
        target_divs = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "#targets-container .target-container")
            )
        )

        # Optional: Check there's at least 2 elements
        if len(target_divs) < 2:
            print("Not enough target divs found!")
            continue

        # 3) Click them in a given order.
        #    For example: second then first (0-based indexing).
        #    Wait until each is clickable before clicking.
        choices = first_group_choices if groups[j] == 0 else second_group_choices
        for target_idx_in_div in choices[i]:
            div = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(target_divs[target_idx_in_div])
            )
            div.click()
            random_sleep()
        # Click submit button
        driver.find_element(By.ID, "submit").click()
        random_sleep()


# Quit all the WebDriver instances
print("\nShutting down the WebDriver instances:")
for driver in tqdm(drivers):
    driver.quit()
