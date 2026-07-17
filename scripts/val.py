import json
reg = json.load(open("docking_registry.json"))
for t in reg["targets"]:
    if t["target_id"] == "cox2":
        t["validated"] = True
        t["reference_rmsd"] = 0.834
        t["enrichment_auc"] = 0.817
        t["enrichment_ef20"] = 2.67
        t["enrichment_n"] = 16
json.dump(reg, open("docking_registry.json", "w"), indent=2)
print("COX-2 validation recorded")