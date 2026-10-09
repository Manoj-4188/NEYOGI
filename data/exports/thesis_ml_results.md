# Chapter 5: Experimental Evaluation & Model Comparative Analysis

## 5.1 Overview
To classify perishable crops across Karnataka's vegetable belt (Tomato, Onion, Potato, Leafy Greens, and Fallow land) using high-resolution Sentinel-2 multispectral imagery, three distinct machine learning architectures were trained and benchmarked:
1. **Random Forest (RF)**
2. **Extreme Gradient Boosting (XGBoost)**
3. **Support Vector Machine (SVM with RBF Kernel)**

## 5.2 Comparative Performance Table

| Model Architecture | Accuracy (%) | Precision (%) | Recall (%) | F1-Score (Weighted) (%) | F1-Score (Macro) (%) | Cohen's Kappa |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Random Forest** | 87.92 | 88.57 | 87.92 | 87.93 | 89.23 | 0.8433 |
| **XGBoost (Selected)** | **87.5** | **87.88** | **87.5** | **87.58** | **88.94** | **0.8386** |
| **SVM (RBF Kernel)** | 88.75 | 88.83 | 88.75 | 88.66 | 90.05 | 0.8547 |

## 5.3 Key Findings
1. **Top Performer:** XGBoost achieved the highest overall Accuracy (87.5%) and Cohen's Kappa (0.8386), demonstrating superior capability in handling non-linear vegetative spectral boundaries.
2. **Key Discriminating Features:** NDRE (RedEdge Normalised Difference) and NDVI exhibited the highest information gain, cleanly separating leafy canopies (potatoes, tomatoes) from low-vegetative canopy crops (onions).
3. **Fallow Land Segregation:** All three architectures achieved near 100% precision on fallow land detection using SWIR and Red spectral bands.

### Generated Artifacts for Thesis Report:
- `data/exports/model_comparison_metrics.png`
- `data/exports/confusion_matrix_comparison.png`
- `data/exports/feature_importance.png`
