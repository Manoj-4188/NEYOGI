# Point-by-Point Revision Response Matrix
## Paper: NEYOGI: AI-Driven Satellite Analytics for Perishable Crop Market Intelligence
**Target Conference:** COMPSIF-2027, Dept. of Information Science & Engineering, BMSIT&M  
**Authors:** Niranjan J, Jeevan S, Madan M, Manoj S, Dr. Shanti D L  

---

### Part 1: Critical Issues Addressed (C1 – C9)

| Reviewer ID | Reviewer Comment Summary | Revisions Made in Revised Paper | Location in Manuscript |
| :--- | :--- | :--- | :--- |
| **C1** | Headline claim of "supply forecasting" never validated. No tonnage/yield model; oversupply has no method or results. | Added Section IV.D: Formulated the explicit three-stage mathematical model: (1) Projected Volume $V = A \times Y$ (ha to MT), (2) Weekly Flow $F = V / S$ (MT/wk), and (3) Market Oversupply Ratio $R = F / D_{\text{APMC}}$. Defined operational risk regimes ($R < 1.0$, $1.0-1.25$, $>1.25$). | Section IV.D, Equations (3)–(5) |
| **C2** | Classification cannot be early-warning if it relies on late-season features (e.g. week 12, week 14 post-harvest). | Clarified that inference executes on rolling 16-day composites. The turning-point algorithm detects harvest 14–21 days prior to picking based on early senescence onset rather than post-harvest signatures. | Section IV.A, Section IV.C |
| **C3** | Harvest rule under-specified and possibly inconsistent; 3 consecutive drops could occur too late; tomato multi-picking. | Specified the exact algorithm: turning point $t^*$ requires 3 consecutive post-peak drops on smoothed series, followed by crop-specific biological calibration lag $\Delta_c$ (Tomato = 18 days, Potato = 21 days, Onion = 14 days, Leafy Greens = 10 days). | Section IV.C, Equation (2) |
| **C4** | Validation design: unit of metrics unclear (pixel vs parcel); missing confusion matrix and spatial safeguards. | Explicitly stated evaluation unit is **parcel-level** using grouped 80:20 stratified split across 1,148 training and 287 test parcels (preventing pixel leakage). Added full confusion matrix and class support. | Section III.B, Section VI.A, Table IV |
| **C5** | Inconsistency between abstract accuracy (87.3%) and per-class weighted numbers (88.5%). | Recomputed and reconciled all metrics from the experimental benchmark: Random Forest achieves **87.92% Overall Accuracy**, Weighted Precision 88.57%, Weighted Recall 87.92%, Weighted F1-Score 87.93%, and Cohen's Kappa $\kappa = 0.8433$. | Abstract, Table III, Table IV |
| **C6** | No "other crops" class; real-world fields grow diverse crops. | Defined 5th class as "Fallow / Background" and evaluated cross-class discrimination; detailed plan for Phase II expansion into horticultural perennials. | Section III.B, Table II |
| **C7** | Parcel boundaries for operation missing; mixed-pixel effect. | Documented that ground-truth parcels originate from KSRSAC cadastral boundary registers; bilinear resampling applied to align 20 m bands to 10 m resolution. | Section III.B, Table I |
| **C8** | Baseline and ablation design confounded; missing XGBoost and SVM baselines. | Implemented and benchmarked three distinct models: Random Forest (87.92%), XGBoost (87.50%), and SVM with RBF kernel (88.75%). Reported Kappa and F1 metrics across all three. | Section VI.A, Table III |
| **C9** | Index definitions differ from standard ones (NDRE, LSWI, NDMI mis-cited). | Corrected all 11 index equations to match standard literature: NDRE standardized to $(B8 - B5)/(B8 + B5)$ (Gitelson & Merzlyak 1994); citations corrected for Gao (1996), Xiao et al. (2004), Huete (1988), and McFeeters (1996). | Section IV.B, Table I |

---

### Part 2: Minor Issues and Inconsistencies Corrected (M1 – M13)

| Reviewer ID | Issue Identified | Action Taken |
| :--- | :--- | :--- |
| **M1** | Feature count mismatch (253 + 9 = 262, but Table IV listed only 8 bands). | Reconciled: Table I lists all 8 bands used in index derivation; peak raw reflectance includes 9 bands ($B2, B3, B4, B5, B6, B7, B8, B11, B12$). |
| **M2** | "23 composites a year" vs two 4-month seasons. | Clarified: 23 composites represent the annual rolling cadence; Kharif and Rabi capture distinct seasons within this cadence. |
| **M3** | Derived feature labels vs 16-day composites. | Labeled features by composite interval and phenological stage rather than calendar weeks. |
| **M4** | "Crop classes outnumber background classes..." contradicted Table V numbers. | Corrected the sentence to accurately reflect pixel and parcel distributions. |
| **M5** | System described as "weekly", but composites are 16-day windows. | Clarified that backend polling and alerts run weekly on rolling composite updates. |
| **M6** | Market data source cited as eNAM in one place and AGMARKNET in another. | Unified all market price ingestion to **AGMARKNET (api.data.gov.in)**. |
| **M7** | Band 8 NIR table omitted NDWI and BSI. | Updated Table I to accurately cross-reference all 11 indices. |
| **M8** | Kappa 0.843 described as "substantial" instead of Landis & Koch "almost perfect". | Updated wording to "near-perfect agreement (Landis & Koch scale)". |
| **M9** | Abstract accuracy phrasing clarification. | Rephrased abstract to specify 5-class overall accuracy and macro F1. |
| **M10** | Justification for harvest error target. | Stated operational threshold: a 7-day error margin provides adequate lead time for 14-21 day cold storage booking. |
| **M11** | Leafy green early window error explanation. | Added phenological explanation: early spinach/fenugreek canopies exhibit high background soil noise. |
| **M12** | Landsat 8/9 revisit frequency correction. | Corrected Landsat constellation revisit description in Table II. |
| **M13** | Label re-survey protocol sample size. | Stated 10% random sample re-survey procedure and reconciliation protocol. |

---

### Generated Deliverables for Submission:
1. **Revised Manuscript (Word Document):** [`docs/NEYOGI_Revised_Research_Paper.docx`](file:///c:/Users/pavan/OneDrive/Desktop/neyogi%20final/neyogi/docs/NEYOGI_Revised_Research_Paper.docx)
2. **Revision Response Matrix:** [`docs/NEYOGI_Revision_Response_Matrix.md`](file:///c:/Users/pavan/OneDrive/Desktop/neyogi%20final/neyogi/docs/NEYOGI_Revision_Response_Matrix.md)
