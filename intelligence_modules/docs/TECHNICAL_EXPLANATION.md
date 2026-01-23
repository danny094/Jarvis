# Causal Intelligence Module: Technical Explanation

## Theoretical Foundation

The CIM is a implementation of **Structural Causal Models (SCM)** within an agentic framework. It is designed to handle the mathematical and logical rigors required to perform **Identification** and **Estimation** of causal effects.

### 1. Directed Acyclic Graphs (DAGs)
Every reasoning path begins with a DAG. The module uses **GraphTraversalTools** to:
*   Identify **Back-door paths** (Non-causal paths that create spurious correlation).
*   Flag **Colliders** (Nodes where two arrows meet; conditioning on these creates bias).
*   Decompose **Direct vs. Indirect Effects** through mediation analysis.

### 2. The do-calculus Implementation
CIM distinguishes between **Conditional Probability** $P(Y | X)$ (Seeing) and **Interventional Probability** $P(Y | do(X))$ (Doing). 
*   In the **Procedural Layer**, the agent identifies if the user's query requires a 'do-operation'. 
*   If so, it invokes the **Minimum Sufficient Adjustment Set** algorithm to identify which confounders must be controlled for to transform the interventional query into an estimable observational query.

### 3. Bias Mitigation Protocols
The system implements industry-standard checks for:
*   **Confounding Bias:** Selection of variables that cause both Exposure and Outcome.
*   **Selection Bias:** Using the `Berkson's Paradox` anti-pattern to detect selection on colliders.
*   **Measurement Error:** Calculating attenuation bias using the `cmt_002` confidence interval tools.

## The Mathematical Registry (`causal_math_registry`)

To prevent the LLM's inherent "math-hallucination" problem, all quantitative steps are offloaded to **Deterministic Engines**:

*   **Metric Estimation:** Uses Cohen's d ($d = \frac{\bar{x}_1 - \bar{x}_2}{s_{pooled}}$) for effect size.
*   **Uncertainty Quantification:** Proper frequentist Confidence Intervals and Bayesian Posterior Updates ($P(H|E) = \frac{P(E|H)P(H)}{P(E)}$).
*   **Path Scoring:** Uses `HypothesisRanking` algorithms to score competing DAG structures based on evidence overlap.

## Discovery vs. Inference

The module supports two distinct operational modes:
1.  **Causal Inference:** Given a DAG and data, estimate the effect. (Uses `PROC001-PROC020`).
2.  **Causal Discovery:** Given only data, find the DAG. (Uses `DISC001-DISC010` like PC or LiNGAM algorithms).

## Key Terminology Used
*   **Exogenous Variables:** Factors originating outside the model (Seasonality, Global Trends).
*   **Endogenous Variables:** Factors determined within the causal system.
*   **Stability/Invariance:** The property where causal links remain constant across different environments/interventions.
