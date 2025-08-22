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

# Define a function for safe element clicking with retry logic
def safe_click(driver, element, max_retries=3):
    """Safely click an element with retry logic to handle interception issues."""
    for attempt in range(max_retries):
        try:
            # Scroll element into view
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            random_sleep(0.1, 0.3)
            
            # Try JavaScript click first
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Failed to click element after {max_retries} attempts: {e}")
                raise
            random_sleep(0.5, 1.0)  # Wait longer before retry
            continue
    return False

REMOTE_WEBDRIVER_URL = 'http://127.0.0.1:4444/wd/hub'  # or your Docker host IP

# Configuration options
USE_LOCAL_FALLBACK = True  # Set to False to only use remote grid
MAX_CONCURRENT_DRIVERS = 20  # Limit concurrent drivers to avoid overwhelming the grid
DRIVER_CREATION_DELAY = 2  # Seconds between driver creations

# Allow environment variable overrides
import os
USE_LOCAL_FALLBACK = os.getenv('USE_LOCAL_FALLBACK', str(USE_LOCAL_FALLBACK)).lower() == 'true'
MAX_CONCURRENT_DRIVERS = int(os.getenv('MAX_CONCURRENT_DRIVERS', MAX_CONCURRENT_DRIVERS))
DRIVER_CREATION_DELAY = int(os.getenv('DRIVER_CREATION_DELAY', DRIVER_CREATION_DELAY))

print(f"Configuration:")
print(f"  USE_LOCAL_FALLBACK: {USE_LOCAL_FALLBACK}")
print(f"  MAX_CONCURRENT_DRIVERS: {MAX_CONCURRENT_DRIVERS}")
print(f"  DRIVER_CREATION_DELAY: {DRIVER_CREATION_DELAY}")
print(f"  REMOTE_WEBDRIVER_URL: {REMOTE_WEBDRIVER_URL}")

# Create multiple instances of headless Chrome
print("Loading headless Chrome instances:")

# First, verify the Selenium Grid is accessible
def verify_grid_connection():
    """Verify that the Selenium Grid is accessible and responsive."""
    try:
        import requests
        response = requests.get(REMOTE_WEBDRIVER_URL.replace('/wd/hub', '/status'), timeout=10)
        if response.status_code == 200:
            print("Selenium Grid is accessible")
            return True
        else:
            print(f"Selenium Grid returned status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error connecting to Selenium Grid: {e}")
        return False

def create_local_driver():
    """Create a local Chrome driver as fallback."""
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Failed to create local driver: {e}")
        return None

# Verify connection before proceeding
grid_accessible = verify_grid_connection()

if not grid_accessible and not USE_LOCAL_FALLBACK:
    print("Selenium Grid is not accessible and local fallback is disabled. Exiting.")
    exit(1)

# Create drivers with retry logic and gradual creation
drivers = []
max_retries = 3
session_timeout = 30  # Increase timeout for session creation

# Limit the number of concurrent drivers to avoid overwhelming the system
actual_instance_count = min(instance_count, MAX_CONCURRENT_DRIVERS)
if actual_instance_count < instance_count:
    print(f"Limiting to {actual_instance_count} concurrent drivers (requested: {instance_count})")

for driver_idx in tqdm(range(actual_instance_count)):
    driver = None
    for attempt in range(max_retries):
        try:
            print(f"Creating driver {driver_idx + 1}/{actual_instance_count} (attempt {attempt + 1})")
            
            if grid_accessible:
                # Try remote driver first
                driver = webdriver.Remote(
                    command_executor=REMOTE_WEBDRIVER_URL,
                    options=chrome_options,
                    desired_capabilities=DesiredCapabilities.CHROME.copy()
                )
            else:
                # Use local driver as fallback
                driver = create_local_driver()
                if not driver:
                    raise Exception("Failed to create local driver")
            
            # Test the driver by getting a simple page
            driver.get("data:text/html,<html><body><h1>Test</h1></body></html>")
            
            drivers.append(driver)
            print(f"Successfully created driver {driver_idx + 1}")
            
            # Add a delay between driver creations to avoid overwhelming the system
            if driver_idx < actual_instance_count - 1:  # Don't sleep after the last driver
                sleep(DRIVER_CREATION_DELAY)
            
            break  # Success, exit retry loop
            
        except Exception as e:
            print(f"Failed to create driver {driver_idx + 1} (attempt {attempt + 1}): {e}")
            
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                driver = None
            
            if attempt == max_retries - 1:
                print(f"Failed to create driver {driver_idx + 1} after {max_retries} attempts")
                
                # Try local driver as last resort if we were using remote
                if grid_accessible and USE_LOCAL_FALLBACK:
                    print(f"Trying local driver as fallback for driver {driver_idx + 1}")
                    try:
                        driver = create_local_driver()
                        if driver:
                            driver.get("data:text/html,<html><body><h1>Test</h1></body></html>")
                            drivers.append(driver)
                            print(f"Successfully created local driver {driver_idx + 1}")
                            continue
                    except Exception as local_error:
                        print(f"Local driver fallback also failed: {local_error}")
                
                print(f"Created {len(drivers)} drivers out of {actual_instance_count} requested")
                
                if len(drivers) == 0:
                    print("No drivers were created. Exiting.")
                    exit(1)
                else:
                    print("Continuing with available drivers...")
                    break
            else:
                print(f"Retrying in 5 seconds...")
                sleep(5)

print(f"\nSuccessfully created {len(drivers)} drivers out of {actual_instance_count} requested")

def check_driver_health(driver, driver_id):
    """Check if a driver is still responsive and healthy."""
    try:
        # Try to get the current URL to check if driver is responsive
        current_url = driver.current_url
        return True
    except Exception as e:
        print(f"Driver {driver_id} is not responsive: {e}")
        return False

def cleanup_failed_drivers():
    """Remove any failed drivers from the list."""
    global drivers
    original_count = len(drivers)
    drivers = [driver for driver in drivers if check_driver_health(driver, drivers.index(driver))]
    if len(drivers) < original_count:
        print(f"Removed {original_count - len(drivers)} failed drivers. {len(drivers)} drivers remaining.")
    return len(drivers) > 0

# Check driver health before proceeding
if not cleanup_failed_drivers():
    print("No healthy drivers remaining. Exiting.")
    exit(1)

# Iterate through the drivers and perform the clicks
print("\nLoading experiment query pages:")
for driver in tqdm(drivers):
    try:
        print(f"Loading query page for driver {drivers.index(driver)}...")
        driver.get(query_url)
        
        # Wait for page to load and verify it's the right page
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        
        # Verify this is actually a query page
        try:
            has_submit = len(driver.find_elements(By.ID, "submit")) > 0
            has_instruction = len(driver.find_elements(By.ID, "instruction-text")) > 0
            
            if not has_submit or not has_instruction:
                print(f"Warning: Driver {drivers.index(driver)} loaded page but missing key elements")
                print(f"  Has submit: {has_submit}, Has instruction: {has_instruction}")
                print(f"  URL: {driver.current_url}")
                print(f"  Title: {driver.title}")
                
                # Try to reload the page
                print(f"  Reloading page...")
                driver.refresh()
                random_sleep(2, 4)
                
                # Check again
                has_submit = len(driver.find_elements(By.ID, "submit")) > 0
                has_instruction = len(driver.find_elements(By.ID, "instruction-text")) > 0
                print(f"  After reload - Has submit: {has_submit}, Has instruction: {has_instruction}")
                
        except Exception as verify_error:
            print(f"Error verifying page for driver {drivers.index(driver)}: {verify_error}")
            
    except Exception as load_error:
        print(f"Error loading query page for driver {drivers.index(driver)}: {load_error}")
        continue

print(f"\nSimulating {actual_instance_count} users conducting the experiment:")
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
        
        # 0) Verify page has loaded and get current URL for debugging
        try:
            current_url = driver.current_url
            page_title = driver.title
            
            # Wait for page to be fully loaded
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Verify this is actually a query page by checking for key elements
            try:
                # Check if we're on the right page by looking for common elements
                page_has_submit = len(driver.find_elements(By.ID, "submit")) > 0
                page_has_instruction = len(driver.find_elements(By.ID, "instruction-text")) > 0
                
                if i == 0 and j == 0:  # Only log for first iteration to avoid spam
                    print(f"Current URL: {current_url}")
                    print(f"Page title: {page_title}")
                    print(f"Page ready state: {driver.execute_script('return document.readyState')}")
                    print(f"Page has submit button: {page_has_submit}")
                    print(f"Page has instruction text: {page_has_instruction}")
                    
                    # Check for JavaScript errors
                    try:
                        js_errors = driver.execute_script("return window.jsErrors || []")
                        if js_errors:
                            print(f"JavaScript errors found: {js_errors}")
                    except:
                        pass
                    
                    # Check console logs
                    try:
                        console_logs = driver.execute_script("return window.consoleLogs || []")
                        if console_logs:
                            print(f"Console logs: {console_logs[:5]}")  # Show first 5 logs
                    except:
                        pass
                
                # If key elements are missing, this might not be the right page
                if not page_has_submit or not page_has_instruction:
                    print(f"Warning: Driver {j} appears to be on wrong page (missing key elements)")
                    print(f"URL: {current_url}")
                    
            except Exception as verify_error:
                print(f"Error verifying page elements for driver {j}: {verify_error}")
                
        except Exception as e:
            print(f"Error getting page info or waiting for page load for driver {j}, iteration {i}: {e}")
            continue
        
        # 1) Wait for the main container to appear with better error handling
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "targets-container"))
            )
        except Exception as e:
            print(f"Timeout waiting for targets-container for driver {j}, iteration {i}: {e}")
            print(f"Driver {j} current URL: {driver.current_url}")
            
            # Try alternative selectors and strategies
            try:
                print(f"Trying alternative strategies for driver {j}...")
                
                # Strategy 1: Try different CSS selectors
                alternative_selectors = [
                    "[id*='targets']",
                    "[class*='targets']",
                    ".targets-container",
                    "[id*='container']",
                    "[class*='container']"
                ]
                
                targets_container = None
                for selector in alternative_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            targets_container = elements[0]
                            print(f"Found container with selector '{selector}': {targets_container.get_attribute('id') or targets_container.get_attribute('class')}")
                            break
                    except:
                        continue
                
                # Strategy 2: Look for any div with target-related content
                if not targets_container:
                    try:
                        all_divs = driver.find_elements(By.TAG_NAME, "div")
                        for div in all_divs:
                            div_id = div.get_attribute('id') or ''
                            div_class = div.get_attribute('class') or ''
                            if 'target' in div_id.lower() or 'target' in div_class.lower():
                                targets_container = div
                                print(f"Found target-related div: id='{div_id}', class='{div_class}'")
                                break
                    except:
                        pass
                
                # Strategy 3: Wait for any element that might be the container
                if not targets_container:
                    try:
                        print(f"Waiting for any container-like element to appear...")
                        WebDriverWait(driver, 15).until(
                            lambda d: len(d.find_elements(By.CSS_SELECTOR, "[id*='target'], [class*='target'], [id*='container'], [class*='container']")) > 0
                        )
                        # Try to find it again
                        for selector in alternative_selectors:
                            try:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                if elements:
                                    targets_container = elements[0]
                                    print(f"Found container after waiting with selector '{selector}'")
                                    break
                            except:
                                continue
                    except:
                        pass
                
                # Strategy 4: Check if page is still loading or has JavaScript errors
                if not targets_container:
                    try:
                        # Check page source for clues
                        page_source = driver.page_source
                        if 'targets-container' in page_source:
                            print(f"targets-container found in page source but not in DOM - JavaScript issue?")
                        elif 'target' in page_source.lower():
                            print(f"Found 'target' in page source - element might have different ID/class")
                        
                        # Check for JavaScript errors
                        js_errors = driver.execute_script("return window.jsErrors || []")
                        if js_errors:
                            print(f"JavaScript errors: {js_errors}")
                        
                        # Check console logs
                        console_logs = driver.execute_script("return window.consoleLogs || []")
                        if console_logs:
                            print(f"Console logs: {console_logs[:5]}")
                        
                        # Strategy 5: Check if elements are being loaded dynamically
                        print(f"Checking for dynamic content loading...")
                        
                        # Look for any script tags that might be loading content
                        script_tags = driver.find_elements(By.TAG_NAME, "script")
                        print(f"Found {len(script_tags)} script tags")
                        
                        # Check for any iframes that might contain the content
                        iframes = driver.find_elements(By.TAG_NAME, "iframe")
                        if iframes:
                            print(f"Found {len(iframes)} iframes - content might be in iframe")
                            for idx, iframe in enumerate(iframes):
                                try:
                                    iframe_src = iframe.get_attribute('src')
                                    print(f"  Iframe {idx}: src='{iframe_src}'")
                                except:
                                    pass
                        
                        # Check for any elements with 'loading' or 'spinner' classes
                        loading_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='loading'], [class*='spinner'], [class*='wait']")
                        if loading_elements:
                            print(f"Found {len(loading_elements)} loading/spinner elements - page might still be loading")
                        
                        # Check if there are any network requests still pending
                        try:
                            pending_requests = driver.execute_script("""
                                if (window.performance && window.performance.getEntriesByType) {
                                    return window.performance.getEntriesByType('resource').filter(r => r.responseEnd === 0).length;
                                }
                                return 0;
                            """)
                            if pending_requests > 0:
                                print(f"Found {pending_requests} pending network requests - waiting for them to complete")
                                # Wait a bit more for network requests to complete
                                random_sleep(3, 5)
                        except:
                            pass
                            
                    except Exception as debug_error:
                        print(f"Error during debugging: {debug_error}")
                
                # If we found a container, update its ID for future use
                if targets_container:
                    try:
                        driver.execute_script("arguments[0].id = 'targets-container';", targets_container)
                        print(f"Updated container ID to 'targets-container'")
                        # Wait a moment for the change to take effect
                        random_sleep(0.5, 1.0)
                    except Exception as update_error:
                        print(f"Error updating container ID: {update_error}")
                else:
                    print(f"No container found with any strategy for driver {j}")
                
            except Exception as alt_error:
                print(f"Alternative strategies failed for driver {j}: {alt_error}")
            
            # Try to refresh the page and wait again
            try:
                print(f"Refreshing page for driver {j}...")
                driver.refresh()
                random_sleep(2, 4)  # Wait longer after refresh
                
                # Wait again for the container with increased timeout
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.ID, "targets-container"))
                )
                print(f"Successfully loaded targets-container after refresh for driver {j}")
            except Exception as refresh_error:
                print(f"Failed to load targets-container after refresh for driver {j}: {refresh_error}")
                
                # Final attempt: check if we're on the right page
                try:
                    current_url = driver.current_url
                    page_title = driver.title
                    print(f"Driver {j} final status - URL: {current_url}, Title: {page_title}")
                    
                    # Check if we have any of the expected elements
                    has_submit = len(driver.find_elements(By.ID, "submit")) > 0
                    has_instruction = len(driver.find_elements(By.ID, "instruction-text")) > 0
                    print(f"Driver {j} - Has submit: {has_submit}, Has instruction: {has_instruction}")
                    
                    if not has_submit and not has_instruction:
                        print(f"Driver {j} appears to be on wrong page - missing all expected elements")
                    
                except Exception as final_check_error:
                    print(f"Error during final check for driver {j}: {final_check_error}")
                
                # Skip this iteration for this driver
                continue

        # 2) Check if this is a trap question by looking for the instruction text
        try:
            instruction_text = driver.find_element(By.ID, "instruction-text").text
            # Trap questions don't have "Here is a list of X targets. Click and choose exactly Y targets."
            # They have custom alt_description text instead
            is_trap_question = "Here is a list of" not in instruction_text and "Click and choose exactly" not in instruction_text
            
            # Log the question type for debugging
            if i == 0 and j == 0:  # Only log for first iteration to avoid spam
                print(f"Question type: {'Trap' if is_trap_question else 'Regular'}")
                print(f"Instruction text: {instruction_text[:100]}...")
        except Exception as e:
            print(f"Error detecting question type: {e}")
            is_trap_question = False

        # 3) Gather the clickable targets inside #targets-container
        #    (all <div class="target-container">).
        #    We'll use a short wait to ensure all child divs are present.
        try:
            target_divs = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "#targets-container .target-container")
                )
            )
            
            # Debug: Check what elements are actually found
            if i == 0 and j == 0:  # Only log for first iteration to avoid spam
                print(f"Found {len(target_divs)} target divs")
                if len(target_divs) > 0:
                    print(f"First target div ID: {target_divs[0].get_attribute('id')}")
                    print(f"First target div class: {target_divs[0].get_attribute('class')}")
        except Exception as e:
            print(f"Error gathering target divs for driver {j}, iteration {i}: {e}")
            
            # Try to debug what elements are actually present
            try:
                targets_container = driver.find_element(By.ID, "targets-container")
                all_children = targets_container.find_elements(By.XPATH, "./*")
                print(f"Driver {j}: targets-container has {len(all_children)} children")
                for idx, child in enumerate(all_children[:5]):  # Show first 5 children
                    print(f"  Child {idx}: tag={child.tag_name}, class={child.get_attribute('class')}, id={child.get_attribute('id')}")
            except Exception as debug_error:
                print(f"Error debugging targets-container contents: {debug_error}")
            
            continue

        # Optional: Check there's at least 2 elements
        if len(target_divs) < 2:
            print("Not enough target divs found!")
            continue

        # 4) Handle target selection based on question type
        choices = first_group_choices if groups[j] == 0 else second_group_choices
        
        try:
            if is_trap_question:
                # For trap questions, only select 1 target
                target_idx_in_div = choices[i][0] % len(target_divs)  # Use modulo to ensure valid index
                if i == 0 and j == 0:  # Only log for first iteration
                    print(f"Trap question: Selecting 1 target (index {target_idx_in_div}) from {len(target_divs)} available")
                
                # Wait for element to be clickable and use safe click
                div = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(target_divs[target_idx_in_div])
                )
                safe_click(driver, div)
                random_sleep()
            else:
                # For regular questions, select multiple targets as before
                if i == 0 and j == 0:  # Only log for first iteration
                    print(f"Regular question: Selecting multiple targets from {len(target_divs)} available")
                
                # Limit the number of targets to select based on available targets
                max_targets_to_select = min(len(choices[i]), len(target_divs))
                for target_idx_in_div in choices[i][:max_targets_to_select]:
                    if target_idx_in_div >= len(target_divs):
                        continue  # Skip if index is out of bounds
                    
                    # Wait for element to be clickable and use safe click
                    div = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable(target_divs[target_idx_in_div])
                    )
                    safe_click(driver, div)
                    random_sleep()
        except Exception as e:
            print(f"Error during target selection for driver {j}, iteration {i}: {e}")
            # Try to continue with the next iteration
            continue
        
        # Click submit button
        try:
            submit_button = driver.find_element(By.ID, "submit")
            safe_click(driver, submit_button)
            random_sleep()
        except Exception as e:
            print(f"Error clicking submit button for driver {j}, iteration {i}: {e}")
            # Try to continue with the next iteration
            continue


# Quit all the WebDriver instances
print("\nShutting down the WebDriver instances:")
for driver in tqdm(drivers):
    driver.quit()
