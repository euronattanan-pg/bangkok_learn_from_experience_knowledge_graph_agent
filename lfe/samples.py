"""Prepared mock cases; missing fields are normalized to null."""
from .schema import normalize_answers


SAMPLES = (
    {
        "id": "capping-torque",
        "name": "H&S Line B7 capping torque",
        "answers": {
            "title": "H&S 1.8L Line B7 Capping Torque Variation & Pump Material Shrinkage",
            "activity": "During the qualification/run for the 1.8L Phase 2 cap change on Line B7, the capping machine suffered significant torque variation (mostly over-torque) and centerline deviations, resulting in production downtime and an approximately 10% defect rate.",
            "quality_impacted": True,
            "quality_details": "Torque out of specification, predominantly over-torque; approximately 10% defect rate.",
            "project": "1.8L Phase 2 (Pump Cap Change)",
            "product": "Head & Shoulders 1.8L",
            "material": "Pump Cap",
            "supplier": "YMP",
            "line": "B7",
            "machine": "Capping Machine",
            "component": "Chute, inner guide, air rejector",
            "downtime_incurred": True,
            "downtime_minutes": 120,
            "product_run": 6000,
            "product_run_context": "Approximately 6,000 bottles (6-ton batch).",
            "defect_count": 500,
            "defect_description": "Torque out of specification, predominantly over-torque, tight cap closure; approximately 500 bottles (approximately 10%).",
            "cause": "Pump heads were molded more than 2 months earlier by YMP; the box date reflected the tube/pump assembly date. A chemical component in the raw resin caused plastic shrinkage after 2 months' storage, reducing cap diameter and creating excessive friction.",
            "cause_confirmed": True,
            "action": "Temporarily raised the torque target to 500 cNm with 100% inspection (no cap breakage); restricted component age to under 2 months before delivery to P&G; the supplier reformulated raw material to eliminate post-molding shrinkage.",
            "action_effective": True,
            "verification": "Subsequent batches with stock under 2 months old and reformulated material had no recurring torque defects.",
            "attachment_description": "Supplier Quality Investigation Report, RCA, EO Sample Comparison Records",
        },
    },
    {
        "id": "belca-vat",
        "name": "BELCA CTMZ-HU VAT",
        "answers": {
            "title": "BELCA at CTMZ-HU - VAT Execution, Machine & Material Learning",
            "activity": "During BELCA VAT/EO testing, the intended VAT test plan could not be fully executed. Machine issues were identified, including inconsistent film feeding and seal jaw interaction with the bottle. L-side and R-side products were impacted, and cracking of the 19 mm film was observed.",
            "quality_impacted": True,
            "quality_details": "L-side/R-side impacted by inconsistent film feeding; 19 mm film cracked.",
            "project": "BELCA",
            "product_context": "New product/SKU not yet launched; name and SKU unknown.",
            "material": "19 mm film",
            "line": "CTMZ-HU",
            "machine": "BELCA Machine",
            "component": "Seal jaw and film-feeding mechanism",
            "downtime_incurred": True,
            "downtime_minutes": 960,
            "product_run_context": "EO testing only, non-commercial lot; quantity unknown.",
            "defect_description": "L-side and R-side impacted by inconsistent film feeding; 19 mm film cracked. Random defects were unquantified.",
            "cause": "Primary cause: Method - VAT test plan could not be completed because the contractor was unavailable at the vendor site. Contributing machine issues: PLC changed from Schneider to ROCKWELL, inconsistent film feeding, and seal jaw interaction with the bottle. Material issue: 19 mm film was too thin and cracked; 25 mm film should have been evaluated before VAT.",
            "action": "Created an in-house web controlling unit to address inconsistent film feeding.",
        },
    },
)


def samples():
    return [{"id": item["id"], "name": item["name"],
             "answers": normalize_answers(item["answers"])} for item in SAMPLES]
