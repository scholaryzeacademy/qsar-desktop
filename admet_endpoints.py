"""
============================================================
  ADMET-AI ENDPOINT MAP  (admet_endpoints.py)
============================================================
  Maps ADMET-AI's output columns to a display group (Absorption /
  Distribution / Metabolism / Excretion / Toxicity), a human label,
  the task type, unit, and 'polarity':
      risk    -> higher value is a concern (toxicity, CYP inhibition)
      benefit -> higher value is favourable (absorption)
      neutral -> a PK number, shown as-is (no colour judgement)

  Edit this file to add/rename endpoints or move them between groups.
  Any ADMET-AI column not listed here is shown under 'Other'.
============================================================
"""

# name : (group, label, task, unit, polarity)
ENDPOINTS = {
    # ---------- Absorption ----------
    "HIA_Hou":                 ("Absorption", "Human intestinal absorption", "class", "prob", "benefit"),
    "Bioavailability_Ma":      ("Absorption", "Oral bioavailability", "class", "prob", "benefit"),
    "Caco2_Wang":              ("Absorption", "Caco-2 permeability", "reg", "log cm/s", "neutral"),
    "Pgp_Broccatelli":         ("Absorption", "P-gp substrate", "class", "prob", "risk"),
    "PAMPA_NCATS":             ("Absorption", "PAMPA permeability", "class", "prob", "benefit"),
    "Solubility_AqSolDB":      ("Absorption", "Aqueous solubility", "reg", "log mol/L", "neutral"),
    "Lipophilicity_AstraZeneca": ("Absorption", "Lipophilicity (logD)", "reg", "logD", "neutral"),
    "HydrationFreeEnergy_FreeSolv": ("Absorption", "Hydration free energy", "reg", "kcal/mol", "neutral"),

    # ---------- Distribution ----------
    "BBB_Martins":             ("Distribution", "Blood-brain barrier penetration", "class", "prob", "neutral"),
    "PPBR_AZ":                 ("Distribution", "Plasma protein binding", "reg", "%", "neutral"),
    "VDss_Lombardo":           ("Distribution", "Volume of distribution (VDss)", "reg", "L/kg", "neutral"),

    # ---------- Metabolism ----------
    "CYP1A2_Veith":            ("Metabolism", "CYP1A2 inhibition", "class", "prob", "risk"),
    "CYP2C19_Veith":           ("Metabolism", "CYP2C19 inhibition", "class", "prob", "risk"),
    "CYP2C9_Veith":            ("Metabolism", "CYP2C9 inhibition", "class", "prob", "risk"),
    "CYP2D6_Veith":            ("Metabolism", "CYP2D6 inhibition", "class", "prob", "risk"),
    "CYP3A4_Veith":            ("Metabolism", "CYP3A4 inhibition", "class", "prob", "risk"),
    "CYP2C9_Substrate_CarbonMangels": ("Metabolism", "CYP2C9 substrate", "class", "prob", "neutral"),
    "CYP2D6_Substrate_CarbonMangels": ("Metabolism", "CYP2D6 substrate", "class", "prob", "neutral"),
    "CYP3A4_Substrate_CarbonMangels": ("Metabolism", "CYP3A4 substrate", "class", "prob", "neutral"),

    # ---------- Excretion ----------
    "Half_Life_Obach":         ("Excretion", "Half-life", "reg", "hr", "neutral"),
    "Clearance_Hepatocyte_AZ": ("Excretion", "Hepatocyte clearance", "reg", "mL/min/kg", "neutral"),
    "Clearance_Microsome_AZ":  ("Excretion", "Microsomal clearance", "reg", "mL/min/kg", "neutral"),

    # ---------- Toxicity ----------
    "AMES":                    ("Toxicity", "Mutagenicity (AMES)", "class", "prob", "risk"),
    "hERG":                    ("Toxicity", "hERG (cardiotoxicity)", "class", "prob", "risk"),
    "DILI":                    ("Toxicity", "Drug-induced liver injury", "class", "prob", "risk"),
    "Carcinogens_Lagunin":     ("Toxicity", "Carcinogenicity", "class", "prob", "risk"),
    "ClinTox":                 ("Toxicity", "Clinical toxicity", "class", "prob", "risk"),
    "Skin_Reaction":           ("Toxicity", "Skin sensitisation", "class", "prob", "risk"),
    "LD50_Zhu":                ("Toxicity", "Acute toxicity (LD50)", "reg", "log(1/(mol/kg))", "neutral"),
    # ---------- Toxicity: Tox21 nuclear-receptor (NR) & stress-response (SR) panel ----------
    "NR-AR":          ("Toxicity", "Androgen receptor (NR-AR)", "class", "prob", "risk"),
    "NR-AR-LBD":      ("Toxicity", "Androgen receptor LBD", "class", "prob", "risk"),
    "NR-AhR":         ("Toxicity", "Aryl hydrocarbon receptor", "class", "prob", "risk"),
    "NR-Aromatase":   ("Toxicity", "Aromatase", "class", "prob", "risk"),
    "NR-ER":          ("Toxicity", "Estrogen receptor (NR-ER)", "class", "prob", "risk"),
    "NR-ER-LBD":      ("Toxicity", "Estrogen receptor LBD", "class", "prob", "risk"),
    "NR-PPAR-gamma":  ("Toxicity", "PPAR-gamma", "class", "prob", "risk"),
    "SR-ARE":         ("Toxicity", "Oxidative stress (ARE)", "class", "prob", "risk"),
    "SR-ATAD5":       ("Toxicity", "Genotoxicity (ATAD5)", "class", "prob", "risk"),
    "SR-HSE":         ("Toxicity", "Heat-shock response", "class", "prob", "risk"),
    "SR-MMP":         ("Toxicity", "Mitochondrial toxicity (MMP)", "class", "prob", "risk"),
    "SR-p53":         ("Toxicity", "p53 stress response", "class", "prob", "risk"),
}

GROUP_ORDER = ["Absorption", "Distribution", "Metabolism", "Excretion", "Toxicity", "Other"]

# risk thresholds (on probability) used to colour classification endpoints
RISK_HIGH = 0.70
RISK_MED = 0.40