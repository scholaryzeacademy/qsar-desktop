from docking import profile as P, pipeline
prof = P.load_profile("cox2")
res = pipeline.redock_reference(
    prof,
    reference_smiles="<RCX SMILES from the RCSB ligand page>",
    crystal_sdf="rcx_crystal.sdf",
)
print(res)