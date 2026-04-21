# IMC Prosperity 4

This repository contains my trading algorithm for the IMC Prosperity 4 competition.  
It implements two market‑making strategies from Rounds 1 and 2: one static (Intarian Pepper Root) and one dynamic (Ash Coated Osmium), built on a shared `ProductTrader` framework.

---

## Architecture Overview

The system is structured around four classes:

### **Trader**
This is the entry point called by the exchange. It initializes product‑specific traders, aggregates their orders, and manages `traderData` persistence.

### **ProductTrader**
A shared base class providing:
- order‑book parsing  
- best bid/ask extraction  
- wall detection  
- position/volume limits  
- helper methods for placing bids/asks  

Both strategies inherit from this class.

### **StaticTrader**
A rule-based market maker designed for stable, wall-driven microstructure (Intarian Pepper Root).


### **DynamicTrader**
A fair-value-tilted market maker designed for products with mild drift and no strong predictability (Ash Coated Osmium).

---

## Intarian Pepper Root Strategy (StaticTrader)

The strategy focuses on exploiting predictable microstructure around the bid/ask walls:

- **Take favourable liquidity**  
  - buy asks below the wall mid  
  - sell bids above the wall mid  

- **Make liquidity near the walls**  
  - overbid the best bid when below mid  
  - undercut the best ask when above mid  

- **Control inventory**  
  - 1‑tick skew toward flattening  
  - soft volume brake to reduce size as inventory grows  

This produces consistent, low‑variance PnL with strong inventory safety.

---

## Ash Coated Osmium Strategy (DynamicTrader)

The strategy centers around maintaining and trading around a fair‑value estimate:

- **EWMA fair value** (alpha = 0.05) updated each round
- **Persists fair value across rounds** using `traderData`    
- **Quotes inside the spread** (best_bid + 1, best_ask − 1)  
- **1‑tick fair‑value bias**  
  - bid more aggressively when price is below fair value  
  - ask more aggressively when price is above fair value  

- **Inventory‑based volume scaling**  
  - reduce size smoothly as position approaches limits  

This keeps the strategy simple, robust, and adaptive without overfitting.

---

## Design Principles

- **Simplicity**: avoid overfitting and unnecessary parameters  
- **Robustness**: prioritize stability over chasing noise  
- **Inventory control**: never allow blow‑ups  
- **Microstructure awareness**: quote where fills are favourable  
- **Clean architecture**: readable, modular, and easy to extend

---
## Acknowledgements
This project was developed referencing the official Prosperity 4 wiki and tested with an open‑source backtesting tool created by the community. Publicly available Prosperity resources from prior years also helped inform the overall approach.
