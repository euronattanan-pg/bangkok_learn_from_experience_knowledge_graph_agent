# FDM BOM Data Structure Reference

**Source**: Enovia BOM Type Hierarchy v1 — single-product analysis  
**Example product**: OLD SPICE MIND AND BODY AP INVISIBLE SOLID CANYON 2.6oz US 12CT (ID: `80848203`)

## Core Concept

FDM organizes all product data as a **BOM (Bill of Materials) tree**. Every node in the tree is a **Part**. Each Part has a fixed **Part Type** that determines its role, its allowed position in the hierarchy, and what child types it may contain. Understanding the Type hierarchy is the prerequisite for correctly querying, interpreting, or comparing any FDM product data.

---

## Section 1 — Part Types

There are **10 Part Types** in FDM. Each type maps to a specific level or material category in the product structure.

| Abbreviation | Part Type (exact API name) | Role in BOM |
|---|---|---|
| **FPP** | Finished Product Part | Root of the BOM tree. Represents one fully defined market SKU. Every BOM has exactly one FPP. |
| **CUP** | pgCustomerUnitPart | Customer unit. The retail-facing pack shipped to a retailer (e.g., a 12-count case). Direct child of FPP. |
| **TUP** | pgTransportUnitPart | Transport unit. The logistics-facing pack (e.g., a pallet). Direct child of FPP. |
| **IPU** | pgInnerPackUnitPart | Inner pack unit. An intermediate packaging layer inside the CUP (e.g., a 3-count inner box). Child of CUP. |
| **COP** | pgConsumerUnitPart | Consumer unit. The smallest unit a consumer buys (a single product). Child of IPU. |
| **MCUP** | pgMasterCustomerUnitPart | Master customer unit. Defines pallet/slot dimension templates. Child of TUP. |
| **PAP** | Packaging Assembly Part | Packaging sub-assembly. A component built from multiple packaging materials (e.g., a nozzle assembly). Child of COP. |
| **PMP** | Packaging Material Part | Packaging material. A leaf-level part (bottle body, label, pump, etc.). Can appear under CUP, IPU, COP, or PAP. |
| **FOP** | Formulation Part | Formulation. A leaf-level part representing a chemical formula. Child of COP. |
| **OPP** | pgOnlinePrintingPart | Online printing part. A leaf-level part for on-line printed items (shipping marks, barcodes). Child of CUP. |

**Key note on PMP**: `Packaging Material Part` is the only type that appears at multiple levels. Its meaning depends on which parent type it is attached to — always check the parent node type to determine context.

**Key note on substitutes**: Any Part node may have `isSubstitute=true`. A substitute node is an alternative to its sibling primary part. Substitutes do not add a new level to the hierarchy; they are alternatives at the same level as the primary node.

---

## Section 2 — Type Hierarchy (Allowed Parent → Child Relationships)

The BOM tree always follows these parent-child relationships. A type may only appear where its parent type permits it.

```
Finished Product Part (FPP)                          ← root; always unique
├── pgCustomerUnitPart (CUP)                         ← retail branch
│   ├── pgInnerPackUnitPart (IPU)
│   │   ├── pgConsumerUnitPart (COP)
│   │   │   ├── Packaging Assembly Part (PAP)
│   │   │   │   └── Packaging Material Part (PMP)    ← leaf
│   │   │   ├── Packaging Material Part (PMP)        ← leaf; may have isSubstitute child
│   │   │   └── Formulation Part (FOP)                ← leaf
│   │   └── Packaging Material Part (PMP)            ← leaf
│   ├── Packaging Material Part (PMP)                ← leaf
│   └── pgOnlinePrintingPart (OPP)                   ← leaf
└── pgTransportUnitPart (TUP)                        ← logistics branch
    └── pgMasterCustomerUnitPart (MCUP)              ← leaf
```

---

## Section 3 — BOM Combination Paths

A **BOM Combination** is one complete type path from the root (FPP) to a leaf node. These are the 7 valid paths in this product's BOM:

| # | Type path (root → leaf) | Leaf type | Material category |
|---|---|---|---|
| 1 | FPP → CUP → IPU → COP → PAP → **PMP** | Packaging Material Part | Sub-assembly components (e.g., bottle body BA, screw, elevator, bottom seal FSEAL, closure CL) |
| 2 | FPP → CUP → IPU → COP → **PMP** | Packaging Material Part | Consumer-unit direct packaging (e.g., label LBWR, carton CPST); may include a substitute node |
| 3 | FPP → CUP → IPU → COP → **FOP** | Formulation Part | Chemical formula — primary focus for BOM comparison |
| 4 | FPP → CUP → IPU → **PMP** | Packaging Material Part | Inner-pack level packaging (e.g., shrink wrap SWR) |
| 5 | FPP → CUP → **PMP** | Packaging Material Part | Customer-unit level packaging (e.g., outer carton CO) |
| 6 | FPP → CUP → **OPP** | pgOnlinePrintingPart | Online-printed items (shipping marks, barcodes) |
| 7 | FPP → TUP → **MCUP** | pgMasterCustomerUnitPart | Transport unit → pallet/slot dimension template |

---

## Section 4 — Full BOM Instance Tree

Complete BOM for example product `80848203`. Format per node: `[Type]  identifier  rev:revision  qty:quantity`. `★` marks `isSubstitute=true` nodes.

```
■ [Finished Product Part]  80848203  rev:001
│  "OLD SPICE MIND AND BODY AP IS CANYON 2.6oz US 12CT"
│
├── [pgCustomerUnitPart]  CUP-00425946  rev:001  qty:1
│   │  "OS MB IS CANYON 2.6oz US 12ct"
│   │
│   ├── [pgInnerPackUnitPart]  IP-00057687  rev:001  qty:4
│   │   │  "OS MB IS CANYON 2.6oz US 3ct"
│   │   │
│   │   ├── [pgConsumerUnitPart]  COP-00376102  rev:001  qty:3
│   │   │   │  "OS MB IS CANYON 2.6oz US"
│   │   │   │
│   │   │   ├── [Packaging Assembly Part]  91748198  rev:002  qty:1
│   │   │   │   │  "UNCS P90X 2.6oz BNWHT GLBRED 56.6mm"
│   │   │   │   ├── [Packaging Material Part]  91622126  rev:003  qty:1  "BA P90X MEDIUM BONE WHITE"
│   │   │   │   ├── [Packaging Material Part]  91622120  rev:002  qty:1  "SCREW P90X MEDIUM BONE WHITE XX"
│   │   │   │   ├── [Packaging Material Part]  92277188  rev:003  qty:1  "ELEVATOR P90X NAT BF XX"
│   │   │   │   ├── [Packaging Material Part]  99545329  rev:003  qty:1  "FSEAL P90X NAT BF XX"
│   │   │   │   └── [Packaging Material Part]  97057084  rev:007  qty:1  "CL P90X GLB RED"
│   │   │   │
│   │   │   ├── [Packaging Material Part]  90218837  rev:003  qty:1  "PSEAL WHT BF rPP"
│   │   │   │   └── [Packaging Material Part]  99958019  rev:006  qty:1  ★ isSubstitute=true
│   │   │   │       "PSEAL WHT BF XX"
│   │   │   │
│   │   │   ├── [Packaging Material Part]  21120173  rev:002  qty:1  "LBWR OS MB IS CANYON 2.6oz US"
│   │   │   ├── [Packaging Material Part]  21107675  rev:002  qty:1  "CPST OS MB IS 24/7 LST FRS GTL SK US"
│   │   │   └── [Formulation Part]  21310360  rev:001  qty:0.08328
│   │   │       "D10-7-12d w/1.25% HYDRO ALOE 2024C FP"
│   │   │
│   │   └── [Packaging Material Part]  99875596  rev:003  qty:0.00215 KG
│   │       "SWR MCG P90X 3CT 5.91in"
│   │
│   ├── [Packaging Material Part]  99903850  rev:004  qty:1
│   │   "CO P90X 2.25-3.4oz US CA LA"
│   │
│   └── [pgOnlinePrintingPart]  21294089  rev:001  qty:1
│       "80848203 OS MB IS CANYON 2.6oz US"
│
└── [pgTransportUnitPart]  TUP-00160485  rev:001  qty:1
    │  "P90X MED LRG 36x7 U1"
    └── [pgMasterCustomerUnitPart]  MCUP-00101160  rev:001  qty:252 mm
        "P90X MED LRG 12ct 206X141X162mm NO PI"
```

---

## Section 5 — Deduplicated Type Tree

The same type tree with duplicate types merged, showing instance counts per type in this example BOM:

```
Finished Product Part  ×1
├── pgCustomerUnitPart  ×1
│   ├── pgInnerPackUnitPart  ×1
│   │   ├── pgConsumerUnitPart  ×1
│   │   │   ├── Packaging Assembly Part  ×1
│   │   │   │   └── Packaging Material Part  ×5  (direct children of PAP)
│   │   │   ├── Packaging Material Part  ×4 primary + ×1 substitute  (direct children of COP)
│   │   │   └── Formulation Part  ×1
│   │   └── Packaging Material Part  ×1  (direct child of IPU)
│   ├── Packaging Material Part  ×1  (direct child of CUP)
│   └── pgOnlinePrintingPart  ×1
└── pgTransportUnitPart  ×1
    └── pgMasterCustomerUnitPart  ×1
```

---

## Section 6 — Structural Rules for FDM API Usage

These rules must be respected when querying, parsing, or comparing FDM BOM data via the API:

1. **Single root**: Every BOM tree has exactly one `Finished Product Part` (FPP) as its root node.
2. **Two top-level branches**: FPP always splits into exactly two branches — `CUP` (retail side) and `TUP` (logistics side).
3. **Leaf node types**: A BOM path always terminates at one of four leaf types: `PMP` (packaging material), `FOP` (formulation), `OPP` (online printing part), or `MCUP` (dimension template).
4. **Substitute nodes**: A node with `isSubstitute=true` is an alternative to the primary node at the same level. It does not represent an additional BOM level. When comparing BOMs, treat substitutes as alternatives to their parent's sibling, not as separate primary materials.
5. **qty units vary by leaf type**: `qty` may be a dimensionless count, a mass (KG), or a length (mm). The unit depends on the leaf node's type and material definition.
6. **PMP appears at multiple levels**: `Packaging Material Part` can be a direct child of CUP, IPU, COP, or PAP. Always inspect the parent node's type to determine which level a PMP belongs to.
7. **Identity = identifier + revision**: Each node has an `identifier` and a `revision`. BOM comparison must check both fields together — a revision change on the same identifier means the component has changed.

