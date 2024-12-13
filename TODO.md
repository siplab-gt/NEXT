# TODO

## 1. Debug Embedding Functionality of Info-Tuple Algorithm

**File:** `ARankB/algs/InfoTuple/myAlg.py`

### Issue

- **Embedding Not Updating:** The embedding does not get updated at all when it should. This was tested by updating using a random matrix, and it worked in that scenario.

### Things I Have Tried

- **Error Handling:**
  - Added a try-except block in the `full_embedding_update` function.
  - The error raised does not get captured by the backend system, possibly due to the original NEXT design.
  
- **Response Validation:**
  - Verified that responses (list of pairwise comparisons) are not the problem by passing in dummy responses. The embedding did not change.
  
- **Timeout Adjustment:**
  - Tested by increasing the timeout duration from 30 seconds to 300,000 seconds. The embedding still did not change.
  
- **Random State Debugging:**
  - Investigated the `rng` (random state) variable in `ARankB/algs/InfoTuple/myAlg.py`.

---

## 2. Debug Variable `rng` (Random State)

**File:** `ARankB/algs/InfoTuple/myAlg.py`

### Issue

- **Fixed Seed Problem:** Having a fixed seed to generate `rng` before burn-in leads to duplicate selected tuples for all queries, which is contrary to the original implementation in the infotuple repository.

### Things to Try

- **Dynamic Seeding:**
  - Use a different seed for each query during the burn-in iteration.
  
- **Ignoring Seeding:**
  - Allow different tuples to be selected for different queries by ignoring seeding. However, this means each participant will face different queries during burn-in.
  
- **Research Seeding Issues:**
  - Investigate why seeding may not work as expected in general scenarios.

---

## 3. Debug `fast_mutual_information/selection_algorithm` in `infotuple.py`

**File:** `infotuple.py`

### Issue

- **Zero-Division Error:** Changing the `num_items` to under 10 leads to a zero-division error.
  
- **Index Out-of-Bound Error:** Changing the `tuple_size` to over 3 leads to an index out-of-bound error when generating constraints. This should not happen given the logic and does not affect my adaptation in NEXT.

---

## 4. Adjust the Current Front-End Design of Infotuple

**File:** `ARankB/widgets/getQuery_widget.html`

### Issues

1. **User Interaction:**
   - **Annoying Target Selection:** Right-clicking and choosing the targets is cumbersome.
   
   - **Submit Button Glitch:** When clicking the submit button for the first time, if clicked too fast or spam-clicked, the second query may get skipped. This issue occurred only once.

2. **ProcessAnswer Access:**
   - **Participant Information Requirement:** Old apps by NEXT do not require `processAnswer` to have access to participant information; however, info-tuple needs it.

### Things to Try

1. **Improving User Interaction:**
   - **Simplify Target Selection:** Remove the context menu and use left-clicking only to (de)select targets.
   
   - **Check HTML Layout:** Ensure that HTML containers do not have overlaps that could be causing issues during the first time submit.
   
   - **Adjust `processAnswer` Arguments:** Possibly modify the default arguments provided to `processAnswer` to prevent skipping queries.

2. **Handling Participant Information:**
   - **Pass `participant_uid`:** Have the frontend pass back `participant_uid` to `processAnswer`. This approach works just fine.

---

## Summary of Debugging Tasks

- **Embedding Functionality:** Investigate why embeddings are not updating despite successful updates with random matrices. Focus on error handling, response validation, timeout settings, and random state management.
  
- **Random State (`rng`):** Address issues with fixed seeds causing duplicate tuple selections by exploring dynamic seeding or alternative approaches.
  
- **Selection Algorithm Errors:** Resolve zero-division and index out-of-bound errors by reviewing the `fast_mutual_information/selection_algorithm` logic.
  
- **Front-End Design Improvements:** Enhance user interactions and ensure seamless submission processes. Additionally, manage participant information requirements effectively.

---

## Additional Notes

- **Error Handling:** Ensure that all try-except blocks are correctly capturing and handling exceptions to prevent silent failures.
  
- **Testing:** Implement comprehensive testing scenarios to replicate and identify issues reliably.
  
- **Documentation:** Keep the documentation updated with any changes made during the debugging process for future reference.

---
