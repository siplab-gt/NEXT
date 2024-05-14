from random import choice
from time import sleep

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
query_url = 'http://localhost:8000/query/query_page/query_page/5c9d71061565ca92b097ff494c969b'
# Replace with number of examples
n = 25
# Create a list to store the WebDriver instances
drivers = []

# Create multiple instances of headless Chrome
for _ in range(instance_count):
    print('loading driver')
    driver = webdriver.Chrome(options=chrome_options)
    drivers.append(driver)

# Iterate through the drivers and perform the clicks
for driver in drivers:
    driver.get(query_url)

for i in range(n):
    for driver in drivers:
    # Wait until the elements with div ids 'left' and 'right' are clickable
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, 'left')))
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, 'right')))

        # Randomly select either 'left' or 'right' element ID for each click
        element_id = choice(['left', 'right'])
        driver.find_element(By.ID, element_id).click()

        sleep(1)

# Quit all the WebDriver instances
for driver in drivers:
    driver.quit()
