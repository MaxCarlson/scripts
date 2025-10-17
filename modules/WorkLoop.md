## LLM Development Work Loop

This document outlines the standard operational cycle for the CLI LLM agent to make incremental, verifiable progress on a project. The process emphasizes **planning, implementation, testing, and commitment** of changes.

---

## The Development Cycle

The agent must repeat the following cycle until the primary goal defined in `plan.txt` is substantially complete or until explicitly instructed to stop.

### Step 1: Analyze & Plan

1.  **Analyze State:** Read and analyze the **current module(s)** being worked on to determine the existing state and recent progress.
2.  **Extrapolate Goal:** Read and analyze the main project **`plan.txt`**. The plan is comprehensive and contains more work than can be done in a single cycle.
3.  **Define Subset:** **Extrapolate a small, discrete, and measurable subset of features or tasks** from `plan.txt` that can be realistically completed in the *current* work loop. This subset must represent **atomic progress** (i.e., a single, small functional change).
4.  **Create Action Plan:** Formulate a detailed, step-by-step **action plan** (in memory, or a temporary scratchpad) to implement *only* the defined subset of features.

### Step 2: Implement Features & Commit

1.  **Implement:** Execute the action plan by making the necessary code changes in the relevant module(s) to **implement the selected subset of features**.
2.  **Stage & Commit Feature:**
    * **Stage** all file changes related *only* to the new feature implementation.
    * **Commit** the staged changes with a concise and descriptive commit message that clearly explains the feature added or bug fixed.

### Step 3: Test & Commit

1.  **Develop Tests:** Write new **unit or integration tests** that specifically cover the functionality added in the previous step.
2.  **Run Tests:** Execute the entire test suite.
3.  **Verify:** **Ensure that all tests, including the newly added ones, are passing.** If any tests fail (including existing ones), return to the code implementation (Step 2) to fix the issue *before* proceeding.
4.  **Stage & Commit Tests:**
    * **Stage** all file changes related *only* to the new tests.
    * **Commit** the staged test changes with a commit message prefixed with "Test: " or similar, clearly indicating the tests written for the new functionality.

### Step 4: Repeat

* **Repeat the cycle** (Start again at Step 1: Analyze & Plan) to select the next small subset of features from `plan.txt` and continue progress.
