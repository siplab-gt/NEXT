# NEXT Development Documentation

## Creating a New Query: Step-by-Step Guide

This guide explains how to create a new query called `newQuery` from scratch, following the hierarchical structure of the NEXT framework. 

### 🎯 **Developer Preparation Requirements**

**Before starting development, you MUST prepare:**
0. **User Documentation & Experience**:
   - Complete the user documentation tutorials
   - Successfully run 2-3 example experiments
   - Understand the basic workflow of creating and managing experiments
   - Familiarize yourself with the participant experience
   - Be comfortable with the web interface and dashboard

1. **Working UI Design**: Have a complete, tested UI design in Javascript for your query interface. This includes:
   - Wireframes or mockups of the user interface
   - User interaction flow and state management
   - Responsive design considerations
   - Accessibility requirements

2. **Algorithm Design** (if implementing active learning):
   - Define your active learning strategy
   - Specify how queries will be generated based on participant responses
   - Design the model update mechanism
   - Plan the convergence criteria

3. **Resource Requirements**:
   - Identify any media files (images, audio, video) your query will use
   - Plan for file storage and delivery mechanisms
   - Consider memory and processing constraints

**⚠️ Critical Note**: The NEXT framework is designed for rapid experimentation. If you don't have a clear UI design and algorithm strategy, you will waste significant time during development.

### Overview

The NEXT framework follows a hierarchical structure where data flows between endpoints in JSON format. Creating a new query involves establishing these endpoints to create a streamlined process that:

1. Initializes the experiment by storing essential parameters
2. Generates queries dynamically for each participant
3. Renders the user interface for participants to interact with
4. Collects and processes participant responses

This endpoint-based architecture enables smooth data flow and experiment management throughout the query lifecycle. To facilitate your task, I will break down the work flow into levels and more specifically, files, that you would necessarily have to edit/rewrite:
1. **Template Level**: A YAML file that contains experiment-related flags and parameters ([Step 1](#step-1-create-the-template-configuration))
2. **App Level**: A YAML file that decides what arguments get passed into/return from which function in the following python file  -> A python file that fetches, processes those arguments and passes them onto a deeper, algo-level handler ([Step 2](#step-2-create-app-configuration--implementation))
3. **Algorithm Level**: A YAML file that decides what arguments get passed into/return from which function in the following python file -> A python file that runs your algorithm to generate the actual query ([Step 3](#step-3-create-algorithm-configuration--implementation))
4. **Widget Level**: A HTML file that renders the query interface based on the result generated from you algorithm ([Step 4](#step-4-create-the-widget-interface))
![FlowChart](picRef/Flow_Chart.png)

The diagram below is the maintained (text-based) version of the flow chart above, extended with the pieces added in 2026: the Prolific ID modal that gates the first `getQuery`, the trap-question branch, and the fact that the participant's `query_id` counter advances in `processAnswer` (see "Framework Contracts" below):

```mermaid
flowchart TB
    Host(["Host"]) -->|"python launch.py yourQuery.yaml"| initExp
    subgraph initExp["initExp"]
        direction TB
        I1["myApp.yaml initExp args"] --> I2["myApp.py initExp()"]
        I2 --> I3["myAlg.py initExp() per algorithm"]
    end
    Participant(["Participant"]) -->|"open query page"| Modal["Prolific ID modal<br>pre-filled from ?participant="]
    Modal -->|"Start"| getQuery
    subgraph getQuery["getQuery"]
        direction TB
        G1["myApp.py getQuery()<br>reads query_id slot k"] --> G2{"trap slot?"}
        G2 -->|"no"| G3["myAlg.py getQuery()<br>active learning selection"]
        G2 -->|"yes"| G4["trap target served<br>algorithm returns nothing"]
        G3 --> G5["getQuery_widget.html rendered"]
        G4 --> G5
    end
    getQuery -->|"next_widget.processAnswer()"| processAnswer
    subgraph processAnswer["processAnswer"]
        direction TB
        P1["myApp.py processAnswer()<br>query_id becomes k+1"] --> P2["myAlg.py processAnswer()<br>updates embedding state"]
    end
    processAnswer -->|"queries remaining"| getQuery
    processAnswer -->|"all answered"| Debrief["debrief screen"]
```

The following sections will provide concrete example for the above illustration. In most cases, since the YAML file defines the parameters that get passed to the corresponding functions in the Python files, **it's crucial that these align properly.** 

### 🚨 **Important Legacy Notes**

Before starting development, please note these critical system constraints and best practices:

#### **Docker Storage Management**
- **Docker storage can overflow during development** - run `docker builder prune` regularly to clear build cache
- Monitor Docker disk usage: `docker system df`
- 🚨 **NEVER run `docker system prune --volumes`, `docker volume prune`, or `docker-compose down`.** All collected experiment data lives in an *anonymous* Docker volume mounted at `/data/db` in the MongoDB container — these commands delete or orphan it, and the next startup silently begins with an **empty database**. See README §4.2 (safe shutdown) and §5 (backup/cleanup/recovery). Safe cleanup is `docker builder prune` (build cache) or `docker image prune` (dangling images only).
- Always use `docker-compose` (v1, with the hyphen), never `docker compose` (v2) — v2 uses different project naming and attaches fresh empty volumes.

#### **Memory Constraints**
- **Each Celery worker has ~5GB free memory** for task processing
- **Query processing tasks must stay within memory limits** or the server will crash
- **Avoid processing large video/audio files** in `getQuery` tasks
- **Stick to maximum image processing** for query generation

#### **Resource Handling Strategy**
- **For video/audio**: Store pre-generated resources on file storage and map to targetset
- **Frontend rendering**: Let the frontend handle video/audio rendering from stored resources
- **Backend extension**: Consider extending backend logic to write generated media to file storage
- **Example**: PAQ implementation had issues with video generation during query processing

#### **Reference Existing Implementations**
- **Study existing apps** like `ARankB`, `PAQ`, `DynamicPAQ` under `apps/` directory
- **Copy and modify** existing widget templates and algorithm patterns
- **Maintain consistency** with the existing system architecture

---

## Step 1: Create the Template Configuration

### 1.1 Create `newQuery.yaml`

Start by creating a new template file `newQuery.yaml` that extends the base configuration and defines your experiment-specific parameters:

```yaml
# Just like a dictionary, throw in your parameters in the form of key-val pair
app_id: newQuery
args:
  alg_list:
    - {alg_id: newAlgo, alg_label: newAlgo_1, test_alg_label: test}
  algorithm_management_settings:
    mode: fixed_proportions
    params:
    - {alg_label: newAlgo, proportion: 1}
  num_tries: 100
  #--------Create args related to your exp--------------------------------#
  your_arg_1: 25
  your_flag_1: true
  #-----------------------------------------------------------------------#
  debrief: Test debrief 
  instructions: Drag the slider until the color on the right matches the color on the left. 
  participant_to_algorithm_management: one_to_many
  # Where you store your resources. You can access them in app level when you see an object called target_manager. Don't have to use them tho.
  targets:
    targetset: 
    - {primary_description: '0', alt_description: '#0047AB', primary_type: 'color', alt_type: ''}
    - {primary_description: '1', alt_description: '#DC143C', primary_type: 'color', alt_type: ''}
    - {primary_description: '2', alt_description: '#438AD2', primary_type: 'color', alt_type: ''}
    - {primary_description: '3', alt_description: '#ED751E', primary_type: 'color', alt_type: ''}
    - {primary_description: '4', alt_description: '#87CEFA', primary_type: 'color', alt_type: ''}
    - {primary_description: '5', alt_description: '#FFD700', primary_type: 'color', alt_type: ''}
```

### 1.2 Understanding YAML Structure

**Key-Value Pairs Under `args`**: These define the parameters that are passed into the corresponding Python function. For example, under `getQuery: args:`, all parameters listed will be passed to the `getQuery()` function.

**Key-Value Pairs Under `rets`**: These define the expected return structure from the Python function.

**Important Keywords**:
- `optional: true` - Parameter is not required
- `type: any` - Parameter can be any data type
- `type: list` - Parameter is a list; use `values:` to specify the type of list elements
- `type: dict` - Parameter is a dictionary; use `values:` to specify the structure
- `type: oneof` - Parameter can be one of several types; use `values:` to specify options

**Example of List Type Specification**:
```yaml
my_list:
  type: list
  values:
    type: str  # Each element in the list is a string
```

**Example of Dict Type Specification**:
```yaml
my_dict:
  type: dict
  values:
    key1:
      type: str
    key2:
      type: num
      optional: true
```

---

## Step 2: Create the App Structure

### 2.1 Create Directory Structure

Copy and paste any query folder inside `/home/ubuntu/NEXT/apps`. Rename it to  `NewQuery` (matching the casing used in the paths below).

### 2.2 Edit `apps/NewQuery/myApp.yaml`

This file defines the app-specific parameters that will be passed to the corresponding functions, `initExp`, `getQuery`, `processAnswer` in your `myApp.py`:

```yaml
extends: [base.yaml]

initExp:
  args:
    app_id:
      values: [NewQuery]
    args:
      values:
        alg_list:
          values:
            values:
              alg_id:
                description: Supported algorithm types for NewQuery
                values: [NewAlgo]
        
        # Your app-specific parameters
        custom_parameter_1:
          description: App-level custom parameter
          type: str
        
        custom_parameter_2:
          description: Another app-level parameter
          type: num
        
        # Standard parameters
        instructions:
          default: "Your custom instructions here"
          optional: true
        
        num_tries:
          default: 25
          optional: true

getQuery:
  args:
    args:
      values:
        participant_uid:
          type: str
          optional: true
        widget:
          type: boolean
          default: false

processAnswer:
  args:
    args:
      values:
        query_uid:
          type: str
        answer:
          description: The participant's response
          type: any
        response_time:
          type: num
          optional: true
```

### 2.3 Edit `apps/NewQuery/myApp.py`

This is the main application logic that handles experiment initialization, query generation, and answer processing. Notice how it is one level above algs. Therefore, it must call its algo-level counterpart by using ```alg()```(see under ```getQuery()```). In fact, NEXT backend needs to calculate performance metrics by tracking time lasted during running ```alg()```. So even if you are doing anything at alg-level, e.g. a dummy algorithm, make sure you call it to avoid backend exception. Additionally, function inside `myApp.py` should only complete tasks that are indifferent to algorithm types, e.g. fetching a specific argument (see under `initExp`), or grabbing the corresponding targets from targetset based on the value returned by calling ```alg()```.

```python
import json
import next.utils as utils
import next.apps.SimpleTargetManager

class MyApp:
    def __init__(self, db):
        self.app_id = 'NewQuery'
        self.TargetManager = next.apps.SimpleTargetManager.SimpleTargetManager(db)

    def initExp(self, butler, init_algs, args):
        """
        Initialize the experiment.
        
        This function is called once when the experiment is created. It sets up:
        - Target management (loading targets from targetset or generating n targets)
        - Algorithm initialization with experiment parameters
        - Experiment-wide configuration
        
        Args:
            butler: Butler object for data management and storage
            init_algs: Function to initialize algorithms with parameters
            args: Arguments from myApp.yaml containing experiment configuration
        """
        exp_uid = butler.exp_uid
        
        # Handle targets
        if 'targetset' in list(args['targets'].keys()):
            n = len(args['targets']['targetset'])
            self.TargetManager.set_targetset(exp_uid, args['targets']['targetset'])
        else:
            n = args['targets']['n']
        
        args['n'] = n
        del args['targets']

        # Prepare algorithm data - extract parameters that should go to algorithms
        alg_data = {}
        algorithm_keys = ['custom_parameter_1', 'custom_parameter_2']  # Add your parameters here
        
        for key in algorithm_keys:
            if key in args:
                alg_data[key] = args[key]

        # Initialize algorithms with the prepared data
        init_algs(alg_data)
        return args

    def getQuery(self, butler, alg, args):
        """
        Generate a query for the participant.
        
        This function is called each time a participant requests a new query. It:
        - Tracks participant progress (query count)
        - Calls the algorithm to generate the query
        - Returns the query data to be rendered by the widget
        
        Args:
            butler: Butler object for data management and storage
            alg: Algorithm instance that implements the query generation logic
            args: Arguments from getQuery request (participant_uid, widget, etc.)
        """
        participant_uid = args.get('participant_uid', butler.exp_uid)
        
        # Track participant's progress using butler.participants.
        # query_id is READ here but INCREMENTED only in processAnswer, so a
        # query that is served but never answered (participant refreshed the
        # page) does not consume the slot - the next getQuery re-serves it.
        if not butler.participants.exists(uid=participant_uid, key='query_id'):
            butler.participants.set(uid=participant_uid, key='query_id', value=1)
        
        query_id = butler.participants.get(uid=participant_uid, key='query_id')
        
        # Get experiment data
        exp_uid = butler.exp_uid
        experiment = butler.experiment.get()
        
        # Prepare data for algorithm
        alg_args = {
            'query_id': query_id,
            'participant_uid': participant_uid,
            # Add any other data your algorithm needs
        }
        
        # Call algorithm to generate query
        alg_response = alg(alg_args)
        
        # Include query_id and total_queries in the returned dict so the query
        # page can resume a refreshed participant at the right position (see
        # "Framework Contracts: refresh-resume" below). total_queries is the
        # number of answers you expect from one participant (num_tries plus
        # trap questions, in ARankB's case).
        alg_response.update({'query_id': query_id,
                             'total_queries': experiment['args']['num_tries']})
        return alg_response

    def processAnswer(self, butler, alg, args):
        """
        Process the participant's answer.
        
        This function is called when a participant submits an answer. It:
        - Advances the participant's query_id counter (answered slots only)
        - Records the answer and response time
        - Updates experiment statistics
        - Calls the algorithm to process the answer (for active learning)
        
        Args:
            butler: Butler object for data management and storage
            alg: Algorithm instance that implements answer processing logic
            args: Arguments from processAnswer request (query_uid, answer, response_time)
        """
        query = butler.queries.get(uid=args['query_uid'])
        experiment = butler.experiment.get()
        
        # query_id counts ANSWERED queries. Incrementing here (not in
        # getQuery) makes a page refresh cost zero queries: the abandoned
        # on-screen query is re-served at the same slot. See apps/ARankB/myApp.py.
        butler.participants.increment(uid=args['participant_uid'], key='query_id')
        
        # Track number of answers
        num_reported_answers = butler.experiment.increment(
            key='num_reported_answers_for_' + query['alg_label'])

        # Process answer with algorithm
        alg({'answer': args['answer']})
        
        return {'answer': args['answer']}

    def getModel(self, butler, alg, args):
        """
        Get the current model state.
        
        This function is called to retrieve the current state of the algorithm/model.
        Useful for:
        - Monitoring experiment progress
        - Debugging algorithm behavior
        - Analyzing model convergence
        
        Args:
            butler: Butler object for data management and storage
            alg: Algorithm instance
            args: Arguments from getModel request
        """
        return alg()

    def format_responses(self, responses):
        """
        Shape query documents into flat rows for the dashboard CSV download.
        
        This function drives the CSV that experimenters download from the
        dashboard (GET /api/experiment/<exp_uid>/participants?csv=1&zip=1 ->
        next/api/resources/participants.py parse_responses -> this method ->
        pandas DataFrame -> csv). It receives the raw query documents and must
        return a LIST OF FLAT DICTS, one per row.
        
        Rules learned the hard way (see apps/ARankB/myApp.py for the full
        reference implementation):
        - Skip documents without an answer (no 'target_winner' key): these are
          queries that were served but never answered, e.g. abandoned by a
          page refresh.
        - Numbers submitted by the browser arrive as floats, numbers from API
          clients as ints - coerce before comparing (int(float(x))).
        - Drop non-scalar keys ('_id', nested target lists) or pandas will
          emit unusable list-valued columns.
        
        Args:
            responses: List of query documents for the experiment
        """
        formatted = []
        for response in responses:
            if 'my_answer_key' not in response:
                continue
            row = {key: value for key, value in response.items()
                   if key not in ('q', '_id', 'target_items')}
            # ...derive any human-readable columns here...
            formatted += [row]
        return formatted
```

### 2.4 Understanding the Butler System

The **Butler** is a data management system that provides persistent storage for your experiment. It has several storage areas:

**`butler.algorithms`**: Store algorithm-specific data that persists across queries
```python
# Store algorithm parameters
butler.algorithms.set(key='custom_parameter_1', value='some_value')

# Retrieve stored data
value = butler.algorithms.get(key='custom_parameter_1')

# Store complex data structures
butler.algorithms.set(key='model_state', value={'weights': [1, 2, 3], 'bias': 0.5})
```

**`butler.participants`**: Store participant-specific data
```python
# Seed participant progress on first contact (in getQuery)
butler.participants.set(uid=participant_uid, key='query_id', value=1)

# Increment counters - do this in processAnswer, NOT in getQuery, so that a
# served-but-unanswered query (page refresh) is re-served instead of burned
butler.participants.increment(uid=participant_uid, key='query_id')

# Check if data exists
if butler.participants.exists(uid=participant_uid, key='query_id'):
    # Do something
```

**`butler.experiment`**: Store experiment-wide data
```python
# Get experiment configuration
experiment = butler.experiment.get()

# Increment experiment counters
butler.experiment.increment(key='total_answers')
```

**`butler.queries`**: Store query-specific data
```python
# Store query data
butler.queries.set(uid=query_uid, key='query_data', value=query_dict)

# Retrieve query data
query = butler.queries.get(uid=query_uid)
```
---

## Step 3: Create Algorithm Configuration & Implementation

### 3.1 Edit `apps/NewQuery/algs/Algs.yaml`

Similarly, this file defines the parameters that will be passed to your algorithm's Python functions:

```yaml
initExp:
  args:
    custom_parameter_1:
      description: Algorithm-specific parameter 1
      type: str
      optional: true
    custom_parameter_2:
      description: Algorithm-specific parameter 2
      type: num
      optional: true
  rets:
    type: bool
    description: Success indicator
    values: true

getQuery:
  args:
    query_id:
      description: Current query identifier
      type: num
    participant_uid:
      description: Participant identifier
      type: str
  rets:
    description: The query dictionary
    type: dict
    values:
      query_data:
        description: The main query data
        type: any
      metadata:
        description: Additional query metadata
        type: dict
        optional: true

processAnswer:
  args:
    answer:
      description: The participant's answer
      type: any
  rets:
    type: bool
    description: Success indicator
    values: true

getModel:
  rets:
    type: dict
    description: Current model state
    values:
      num_reported_answers:
        description: Number of answers processed
        type: num
      model_state:
        description: Current model state
        type: any
        optional: true
```

### 3.2 Edit `apps/NewQuery/algs/NewAlgo/myAlg.py`

This is where your core algorithm logic lives. Import any dependencies on the top of the file. Make sure to add new library under pip install at `/home/ubuntu/NEXT/next/base_docker_image/requirements.txt` so that you rebuild docker, these dependencies get installed.

```python
import numpy as np
import json
import next.utils as utils

class MyAlg:
    def initExp(self, butler, custom_parameter_1=None, custom_parameter_2=None):
        """
        Initialize the algorithm.
        
        This function is called once when the experiment is created. Use it to:
        - Store algorithm parameters in butler.algorithms
        - Initialize algorithm state
        - Set up any data structures needed for query generation
        
        Args:
            butler: Butler object for data management
            custom_parameter_1: Your first custom parameter
            custom_parameter_2: Your second custom parameter
        """
        # Store parameters in algorithm storage
        butler.algorithms.set(key='custom_parameter_1', value=custom_parameter_1)
        butler.algorithms.set(key='custom_parameter_2', value=custom_parameter_2)
        butler.algorithms.set(key='num_reported_answers', value=0)
        
        # Initialize any other algorithm state
        butler.algorithms.set(key='algorithm_state', value={})
        
        return True

    def getQuery(self, butler, query_id, participant_uid):
        """
        Generate a query for the participant.
        
        This is where your core algorithm logic lives. For active learning:
        - Use participant responses to determine the next best query
        - Implement your query selection strategy
        - Generate query data that will be rendered by the widget
        
        Args:
            butler: Butler object for data management
            query_id: Current query identifier
            participant_uid: Participant identifier
        """
        # Get stored parameters
        custom_param_1 = butler.algorithms.get(key='custom_parameter_1')
        custom_param_2 = butler.algorithms.get(key='custom_parameter_2')
        
        # Your query generation logic here
        # This is where you implement your specific algorithm
        
        # Example: Generate a simple query
        query_data = {
            'question': f"Query {query_id} for participant {participant_uid}",
            'options': ['Option A', 'Option B', 'Option C'],
            'custom_param': custom_param_1
        }
        
        metadata = {
            'query_id': query_id,
            'participant_uid': participant_uid,
            'timestamp': utils.datetimeNow()
        }
        
        return {
            'query_data': query_data,
            'metadata': metadata
        }

    def processAnswer(self, butler, answer):
        """
        Process the participant's answer.
        
        This function is called after each answer submission. For active learning:
        - Update your model based on the answer
        - Store the answer for future query generation
        - Update algorithm state
        
        Args:
            butler: Butler object for data management
            answer: The participant's answer
        """
        # Increment answer counter
        current_count = butler.algorithms.get(key='num_reported_answers')
        butler.algorithms.set(key='num_reported_answers', value=current_count + 1)
        
        # Your answer processing logic here
        # Update algorithm state based on the answer
        
        algorithm_state = butler.algorithms.get(key='algorithm_state')
        algorithm_state[f'answer_{current_count}'] = answer
        butler.algorithms.set(key='algorithm_state', value=algorithm_state)
        
        return True

    # Not essential but useful. Tells you when to report.
    def getModel(self, butler):
        """
        Get the current model state.
        
        This function returns the current state of your algorithm/model.
        Useful for:
        - Debugging algorithm behavior
        - Monitoring convergence
        - Analyzing experiment progress
        
        Args:
            butler: Butler object for data management
        """
        num_answers = butler.algorithms.get(key='num_reported_answers')
        algorithm_state = butler.algorithms.get(key='algorithm_state')
        
        return {
            'num_reported_answers': num_answers,
            'model_state': algorithm_state
        }
```

---

## Step 4: Create the Widget Interface

### 4.1 Edit `apps/NewQuery/widgets/getQuery_widget.html`

This is the final step where you integrate the user interface that renders your query. It should be standard a HTML, CSS, Javascript all in one Jinja 2 template.To better explain how it would look like, an UI rendered by `apps/ARankB/widgets/getQuery_widget.html` is attached below. ![ARankB_UI_Illustration](picRef/ARankB_UI_Illustration.png) Note that you do not have to understand the entire functionality of this particular file as your query will more than likely look and work very differently from it. The goal is to give you a big picture.

**⚠️ Key Takeaway**: 
1. Your UI is inserted into a larger frame created by `next/query_page`. When your implementation fails, the `widget_failure()` function in `next_widget.js` will be triggered, showing a pre-coded debrief screen. Study `next_widget.js` to understand the integration points and error handling.
2.  To access an argument within the dictionary returned from `getQuery()` that you wrote at app level, use `{{query.your_arg}}`.
3. In your `submit()` function, make sure to call `next_widget.processAnswer(participant_response)`.
4. The query page (`next/query_page/templates/query_page.html`) has **four terminal states**: (a) the success debrief after the last answer, (b) an immediate debrief when a finished participant reloads the page (`query_id > total_queries`), (c) `widget_failure()` → failure debrief on any failed request (this includes an expelled trap-failing participant), and (d) the pre-experiment Prolific ID modal that gates everything. Your experiment template should therefore always define all four yaml keys: `debrief`, `debrief_fail`, `debrief_link`, `debrief_link_fail` — a template with only `debrief` renders empty strings for the rest.

---

## Framework Contracts (added 2026)

These are page-level behaviors every app developer should know about. They live in `next/query_page/templates/query_page.html` and the API layer, not in your app — but your app's `getQuery`/`processAnswer` decide whether your experiment benefits from them.

### Participant identity and the Prolific ID modal

Participants are identified by an ID they confirm in a modal **before the first query**:

1. The query page URL may carry `?participant=<ID>` (e.g. appended by a Qualtrics end-of-survey redirect). `next/query_page/query_page.py` reads it and pre-fills the modal input.
2. The participant confirms or types their ID (validated against `/^[A-Za-z0-9]+$/`); nothing is requested from the server until they press Start.
3. The confirmed value is sent as `participant_uid` with every `getQuery`, and the server prefixes it with the experiment UID (`next/api/resources/get_query.py`), so the stored/exported value is `EXPUID_ENTEREDID`. Your widget must echo `{{ query.participant_uid }}` (already prefixed) in its `processAnswer` calls.
4. The ID lands on every query document and flows into the JSON/CSV exports — that is the entire linking mechanism to external systems like Prolific.

⚠️ Only `query_page.html` has this flow. The legacy templates `query_page_popup.html` and `queries_unlimited.html` still generate a **random** 30-character ID on every page load (no resume, no linking) — do not send participants there.

### The refresh-resume contract

The page derives the participant's remaining-query countdown from the server on every query, so a page refresh resumes instead of restarting:

```mermaid
flowchart TD
    A["Query k shown on screen<br>server counter = k"] --> B{"What does the<br>participant do?"}
    B -->|"answers"| C["Counter moves to k+1"]
    B -->|"refreshes the page"| D["Counter stays at k<br>nothing was consumed"]
    D --> E["Query k is served again<br>zero progress lost"]
    E --> B
    C --> F{"Was that the<br>last query?"}
    F -->|"no"| A
    F -->|"yes"| G["Debrief shown"]
    G -.->|"revisits the page later"| H["Counter is already past the total<br>debrief shown immediately"]
```

What your app must do to opt in (ARankB is the reference):
- Return `query_id` and `total_queries` from `getQuery`. The page then computes `tries = total_queries - query_id` after every query, and `tries < 0` sends a finished participant straight to the debrief.
- Seed the counter in `getQuery` but **increment it only in `processAnswer`** — that is what makes a served-but-unanswered query re-servable rather than burned.
- Apps that return neither field fall back to the legacy behavior: a client-side countdown seeded from `num_tries` that restarts on every page load.

### Trap questions (ARankB reference implementation)

Attention checks that are visually indistinguishable from real queries:

```mermaid
flowchart TD
    subgraph browser["In the browser"]
        A["Trap slot reached"] --> B["Question shown in the<br>purple Target card"]
        B --> C["Options shuffled into the pool<br>as normal-looking cards"]
        C --> D["Participant moves 1+ cards<br>into the rank box"]
        D --> E{"Correct option<br>leftmost?"}
    end
    E -->|"yes"| F["trapped = false"]
    E -->|"no"| G["trapped = true"]
    subgraph server["On the server"]
        F --> H["Answer recorded<br>next query served"]
        G --> I["num_trapped + 1"]
        I --> J{"Tolerance<br>exceeded?"}
        J -->|"no"| H
        J -->|"yes"| K["participant_failed<br>failure debrief shown"]
    end
```

Key facts:
- **Data format** (targetset entries after the regular targets): `primary_description` is the comma-separated option list and **the first option is the correct answer**; `alt_description` is the question shown in the anchor card. The separator is exactly `", "`.
- **Scheduling** is a pure function of the participant's `query_id` (`apps/ARankB/myApp.py`), so a refreshed participant sees the trap at the same slot. `total_queries = num_tries + trap_count`.
- **Scoring is client-side**: the widget accepts any submission with **at least one** card in the rank box and checks whether the leftmost card's text equals the correct option, sending only the boolean. The payload is always the sentinel `target_winner=[0]` plus `trapped` — trap answers contribute **nothing** to the active-learning algorithm (the comparison lists extract empty from `[0]`), they only advance the head counter.
- **Escape/expulsion** (`myApp.processAnswer` + `myAlg.processAnswer`): each wrong trap increments `num_trapped`; reaching `tolerance × num_trap_questions` sets `participant_failed`, and with `expel: true` the offending answer raises — the failed request triggers `widget_failure()` and the participant lands on the failure debrief.
- **Persistence and export**: `processAnswer` writes `trapped` and `num_trapped_so_far` onto the answered query document, so the per-trap outcome survives into both JSON and CSV. The participants export additionally joins the participants collection (scalar projection only — participant docs also carry pickled embeddings that must never reach JSON) to produce per-participant aggregates: a `participant_summaries` key in the JSON and `participant_num_trapped` / `participant_failed_final` / `participant_traps_seen` / `participant_traps_answered` columns in the CSV, which populate for pre-existing experiments too. Trap rows keep `isTrap=True` with intentionally blank ranking columns. Caveat: when `expel: true` fires, the fatal trap's `trapped` field never lands on its query document (the raise happens first) — the aggregates are authoritative.

### Background jobs: sync queues and one-step-ahead precompute

Two celery worker pools exist (counts are env vars consumed by `next/broker/next_worker_startup.sh`): **async workers** all consume one shared queue and handle every HTTP-facing task (`getQuery`, `processAnswer`, `getModel`), while **sync workers** each own a private queue (`sync_queue_k@<host>`) for background jobs. `broker.applySyncByNamespace` assigns each *namespace* to a queue round-robin and every job in a namespace runs FIFO on that one concurrency-1 worker — that ordering guarantee is the platform's only serialization primitive (it is how `full_embedding_update` has always run, namespace = `expuid_alglabel`).

⚠️ **Routing (fixed 2026):** the sync queues were historically bound to a single **fanout** exchange, so every sync job was delivered to — and executed by — *every* sync worker (`CELERY_SYNC_WORKER_COUNT`× duplicated work). `next/constants.py` now declares a **direct** exchange (`sync_direct@<host>`) with per-queue routing keys; a job runs exactly once. The new exchange name is deliberate: an existing exchange's type cannot be redeclared, so the old fanout exchange is simply left unused.

**One-step-ahead precompute (ARankB + InfoTuple, `precompute: true` in the experiment config, default off).** The InfoTuple selection takes seconds per query; without precompute the participant's browser blocks on it after every answer. With the flag on, serving query *i* schedules a background job — namespace `expuid_participantuid`, so different participants' jobs parallelize across the sync workers while one participant's jobs stay ordered — that computes the selection for the participant's *predicted next state* and stores it on their participant document (`precomputed_query` = `{head, curr_iteration, tuple, computed_at}`).

The serve path is **consume-if-present**: it uses the stored tuple only when the document's state token (`curr_iteration * n + head`) equals the participant's current token, and otherwise computes inline exactly as before — every failure mode of the background machinery degrades to the pre-feature latency, never to wrong data. Specifics worth knowing before touching this code:

- **Prediction steps over traps.** Trap slots consume an answer (the head advances) without needing a tuple, so the target is the next *non-trap* query id. The trap-slot decision is a pure function of `query_id` shared between serving and prediction (`MyApp._is_trap_slot` / `_trap_schedule`) — they cannot disagree.
- **Guards** that skip scheduling: target query past `total_queries` (note: the *last* query IS a trap whenever `num_tries` is divisible by `num_trap_questions`); participant already `participant_failed` (their head freezes when `expel: false`, so predictions would never match again); predicted state still in burn-in (instant to serve inline); and any prediction that crosses the anchor-cycle **wrap**, where `incremental_embedding_update` refreshes the participant embedding — controlled by `PRECOMPUTE_ACROSS_WRAP` in `apps/ARankB/algs/InfoTuple/myAlg.py` (default `False` = skip, keeping results identical to inline; flip for max speed at the cost of a one-cycle-stale embedding on that single query).
- **Consume is peek-then-take**: a document for a *future* state (a page refresh re-serving the current query) is deliberately kept, not discarded, and covered targets are not re-scheduled. Past-state documents are discarded. The background job itself abandons without computing if the participant has already reached its target (`Butler` reads are non-atomic across the wrap; a torn read only wastes one compute, it cannot corrupt state).
- **The flag is plumbed through `apps/ARankB/myApp.yaml` only** (initExp args are strictly schema-verified, so the key must exist there). Do **not** add an `args:` block to `Algs.yaml`'s `getQuery` — alg getQuery kwargs are intentionally unverified, and declaring them would break the existing `isTrap` call. RandomSampling does not support the trap/precompute kwargs.
- **Monitoring**: the worker logs one line per event — `PRECOMPUTE SCHEDULED / DONE / HIT / STALE / FUTURE / ABANDONED / SKIP-WRAP` — grep `docker logs` of the worker container for `PRECOMPUTE`. (Celery's logger prints each line once per worker process; dedupe by job id when counting.)

Design rationale, edge-case verification, and a 30-participant load test with sizing guidance live in `PRECOMPUTE_REPORT.md` at the repository root.

---

## Step 5: Testing Your Implementation

### 5.1 Start an Experiment

1. **Launch the experiment** using your `newQuery.yaml` template:
   ```bash
   cd examples/
   python launch.py path/to/newQuery.yaml 
   ```

2. **Access the experiment** through the web interface at the provided URL.

### 5.2 Debugging and Error Handling

**All errors are displayed in the web interface:**

1. Go to your experiment page
2. Click on **"Backend Exceptions"** to view any errors
3. The error messages will show exactly what went wrong and where

**Common debugging steps:**

1. **Check YAML alignment**: Ensure parameters in YAML files match function signatures in Python files
2. **Verify imports**: Make sure all `__init__.py` files are created
3. **Check parameter types**: Ensure data types match between YAML and Python
4. **Review butler usage**: Verify correct usage of the butler object for data storage/retrieval
5. **Widget debugging**: Check browser console for JavaScript errors
6. **Memory monitoring**: Monitor memory usage during query processing

**Example error debugging:**
- If you see "Parameter 'custom_parameter_1' not found", check that it's defined in both `myApp.yaml` and `Algs.yaml`
- If you see "TypeError in getQuery", verify that the function signature matches the parameters defined in `Algs.yaml`
- If you see memory issues, check that your query processing stays within the 5GB limit

### 5.3 Memory Management and Video Processing

**⚠️ Critical Memory Context**: During development of a video PAQ implementation, processing even a 3-second video consumed excessive memory, causing the entire instance to become unresponsive, including SSH access. This demonstrates the severe memory constraints of the system.

**Memory Management Best Practices**:
1. **Stay within 5GB limit** per Celery worker
2. **Avoid video/audio processing** during query generation
3. **Use file storage** for large media resources
4. **Let frontend handle rendering** of media files

**Future Solution for Video Processing**:
For any active learning query involving video generation, the **only viable solution** is to:

1. **Pre-generate all videos** before query time
2. **Write videos to file storage** on the instance
3. **Compress videos** (compressed videos take very little storage)
4. **Rewrite backend application** to support file writing to the instance
5. **Map pre-generated videos** to target sets

This approach ensures that query generation remains fast and memory-efficient while still supporting video-based experiments.

### 5.4 Inspecting the Database (Developer Quick Reference)

All experiment data lives in MongoDB inside the `local_mongodb_1` container. The image ships **`mongosh` only** — the legacy `mongo` shell does not exist, and any old snippet using it will fail.

```mermaid
flowchart LR
    B["Browser<br>participants + dashboard"] --> N["nginx"]
    N --> A["API server<br>Flask + gunicorn"]
    A -->|"getQuery / processAnswer"| QA["async@host<br>direct, one shared queue"]
    QA --> WA["Async workers<br>HTTP-facing tasks"]
    WA -->|"background jobs<br>(embedding updates, precompute)"| QS["sync_direct@host<br>direct, routing key per queue"]
    QS --> WS["Sync workers<br>one private queue each<br>FIFO per namespace"]
    WA --> DB
    WS --> DB
    A -->|"JSON / CSV downloads"| DB
    subgraph DB["MongoDB - anonymous volume /data/db - never prune"]
        D1["app_data<br>queries, participants,<br>experiments, algorithms"]
        D2["logs<br>timings + exceptions"]
    end
```

Where things live: `app_data` holds one document per query (including the answer and `participant_uid`) in `<app>:queries`, per-participant state (`query_id`, algorithm state such as embeddings) in `<app>:participants`, experiment configs in `<app>:experiments`, model state in `<app>:algorithms`, plus global `experiments_admin` (the experiment index) and `targets` (target sets, re-inserted per launch). `logs` grows fastest (`ALG-DURATION` per algorithm call).

Quick inspection (read-only, safe while an experiment runs):

```bash
# collection counts and sizes
docker exec local_mongodb_1 mongosh app_data --quiet --eval 'db.getCollectionNames().forEach(c=>print(c, db[c].countDocuments({}), (db[c].stats().storageSize/1048576).toFixed(1)+"MB"))'

# list experiments, newest first
docker exec local_mongodb_1 mongosh app_data --quiet --eval 'db.experiments_admin.find({},{exp_uid:1,app_id:1,start_date:1}).sort({start_date:-1}).forEach(printjson)'

# backup everything (lands on the host at NEXT/local/backup_YYYY-MM-DD/)
docker exec local_mongodb_1 mongodump --host 127.0.0.1 --port 27017 --out /next_backend/local/backup_$(date +%F)
```

For cleanup between data collections and recovery of orphaned volumes, follow README §5 — those procedures are deliberately documented once, in the user guide, because they delete data.

---

## Step 6: Using stress_test.py

`local/stress_test.py` simulates N participants answering an ARankB experiment **simultaneously**, one thread and one headless-Chrome session per participant. Each simulated participant goes through the real flow: the Prolific ID modal (distinct alphanumeric ID per driver), normal queries (ranks all cards), and trap questions (detected via the `#target-trap` element and answered with the flexible one-card rule; a configurable number of drivers answer traps *wrongly* to exercise trap counting and expulsion under load).

### 6.1 Browser runtime

The script targets a disposable Selenium container — never part of the NEXT compose stack:

```bash
docker run -d --name selenium-load --shm-size=2g -p 4444:4444 \
    -e SE_NODE_MAX_SESSIONS=32 -e SE_NODE_OVERRIDE_MAX_SESSIONS=true \
    selenium/standalone-chrome
# ... run the test, then:
docker rm -f selenium-load
```

### 6.2 Running

```bash
cd local/
./local-venv/bin/python stress_test.py EXP_UID \
    --base=http://172.17.0.1:8000 --drivers=30 --wrong-trap-drivers=2 \
    --min-wait=10 --max-wait=20 --max-queries=40 --tag=run1
```

`--base` must be reachable **from inside the Selenium container** — the docker bridge address (`172.17.0.1`) with the backend's direct port, or the instance's public IP; `127.0.0.1` will not resolve to the host from the container. `--min/max-wait` is per-answer think time (realistic pacing matters: precompute hit rates depend on it), `--max-queries` caps answers per driver, `--wrong-trap-drivers=K` makes the first K drivers answer every trap incorrectly.

### 6.3 Output

- `stress_<tag>_latencies.csv` — one row per answer: driver, query number, normal/trap, and the participant-experienced **submit → next-query-rendered latency**; a p50/p95/max summary prints at the end.
- `stress_<tag>_events.log` — per-driver lifecycle notes (start, expulsion/debrief reached, timeouts).
- Server-side counterparts to correlate with: `docker logs` of the worker container (`PRECOMPUTE` lines, task durations), RabbitMQ queue depths (`rabbitmqctl list_queues`), and cAdvisor for per-container CPU/memory.

For a worked 30-participant example with results and interpretation, see `PRECOMPUTE_REPORT.md`.

---

## Parameter Alignment Checklist

Before testing, verify these alignments:

### ✅ Template → App Level
- `newQuery.yaml` parameters → `myApp.yaml` parameters
- `app_id` values match
- Required parameters are defined in both files

### ✅ App Level → Algorithm Level  
- `myApp.yaml` parameters → `Algs.yaml` parameters
- Function signatures in `myApp.py` match YAML definitions
- Algorithm keys are properly extracted and passed

### ✅ Algorithm Level → Implementation
- `Algs.yaml` parameters → `myAlg.py` function signatures
- Return types match expected formats
- Butler storage keys are consistent

### ✅ Widget Level → Algorithm Output
- Widget template variables match algorithm return structure
- Data types are compatible between backend and frontend
- Error handling is implemented in both layers

### ✅ Data Flow Verification
- Parameters flow correctly from YAML → Python functions
- Return values match expected structures
- Error handling is in place at each level
- Memory usage stays within 5GB limit per worker

---

## Best Practices

1. **Start Simple**: Begin with minimal parameters and add complexity gradually
2. **Test Incrementally**: Test each layer independently before integration
3. **Use Descriptive Names**: Make parameter and function names self-documenting
4. **Handle Errors Gracefully**: Implement proper error handling at each level
5. **Document Assumptions**: Comment your code to explain the expected data flow
6. **Version Control**: Use meaningful commit messages when making changes
7. **Memory Management**: Monitor memory usage and stay within 5GB limit per worker
8. **Docker Maintenance**: Run `docker builder prune` regularly to prevent storage overflow — never `--volumes`, `docker volume prune`, or `docker-compose down` (they destroy/orphan the MongoDB data volume; see the Docker Storage Management note above)
9. **Resource Strategy**: Store large media files and let frontend handle rendering
10. **Reference Existing Code**: Study and adapt patterns from existing apps like ARankB, PAQ

---

## Legacy System Notes

### **System Architecture**
- **Backend**: Maintains existing structure and implementation patterns
- **Frontend**: Widgets handle rendering and user interaction
- **Storage**: Butler system manages data persistence
- **Workers**: Celery workers handle task processing with memory constraints

### **Development Workflow**
1. **Study existing apps** (`ARankB`, `PAQ`, `DynamicPAQ`) for patterns
2. **Copy and modify** existing templates and implementations
3. **Maintain consistency** with the current system architecture
4. **Test thoroughly** to ensure compatibility with existing infrastructure

### **Performance Considerations**
- **Memory limits**: Each worker has ~5GB available memory
- **Processing constraints**: Avoid heavy computation in query generation
- **Storage strategy**: Use file storage for large media resources
- **Caching**: Leverage existing caching mechanisms where appropriate

This documentation provides a complete roadmap for creating new queries in the NEXT framework while respecting the existing system architecture and constraints. Follow each step carefully and ensure parameter alignment at every level. 