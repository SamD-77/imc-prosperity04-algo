from datamodel import OrderDepth, TradingState, Order
import json

from typing import List, Dict

# Global variables
STATIC_SYMBOL = "INTARIAN_PEPPER_ROOT"
DYNAMIC_SYMBOL = "ASH_COATED_OSMIUM"

POS_LIMITS = {
    STATIC_SYMBOL: 80,
    DYNAMIC_SYMBOL: 80,
}


class ProductTrader:
    """
    Minimal base class providing shared utilities for product-specific traders.
    """

    def __init__(self, name, state, new_trader_data):
        self.name = name
        self.state = state
        self.new_trader_data = new_trader_data # dictionary to store any data that needs to be passed between rounds
        self.last_traderData = self._load_trader_data()
        self.orders = [] # list of orders to be sent to the exchange

        # Position info
        self.position_limit = POS_LIMITS.get(self.name, 0) 
        self.initial_position = self.state.position.get(self.name, 0)

        # Market data
        self.mkt_buy_orders, self.mkt_sell_orders = self._get_order_depth() 
        self.bid_wall, self.wall_mid, self.ask_wall = self._get_walls()
        self.best_bid, self.best_ask = self._get_best_bid_ask()

        # Volume constraints
        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self._get_max_allowed_volume() # gets updated when order created


    def _load_trader_data(self):
        """
        Loads traderData from the previous round (JSON string -> Dict).
        Returns {} if no traderData is available.
        """                  
        try:
            if self.state.traderData:
                return json.loads(self.state.traderData)
        except:
            pass
        return {}


    #-------- MARKET DATA PROCESSING UTILITIES ---------- #
    def _get_best_bid_ask(self):
        """
        Returns (best_bid, best_ask) from the order book.
        """
        best_bid = best_ask = None

        try:
            if len(self.mkt_buy_orders) > 0:
                best_bid = max(self.mkt_buy_orders.keys())
            
            if len(self.mkt_sell_orders) > 0:
                best_ask = min(self.mkt_sell_orders.keys())
        except: pass

        return best_bid, best_ask


    def _get_walls(self):
        """
        Returns (bid_wall, wall_mid, ask_wall):
        - bid_wall: lowest buy price
        - ask_wall: highest sell price
        - wall_mid: midpoint between the two
        """
        bid_wall = wall_mid = ask_wall = None

        try: bid_wall = min([x for x,_ in self.mkt_buy_orders.items()])
        except: pass
        
        try: ask_wall = max([x for x,_ in self.mkt_sell_orders.items()])
        except: pass

        try: wall_mid = (bid_wall + ask_wall) / 2
        except: pass

        return bid_wall, wall_mid, ask_wall
    

    def _get_max_allowed_volume(self):
        """
        Computes the maximum allowed buy/sell volume based on the position limit and initial position.
        Max allowed volume is the amount that can be traded without exceeding the position limit (e.g. 10 long/short for pos lim 10)
        """
        max_allowed_buy_volume = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position

        return max_allowed_buy_volume, max_allowed_sell_volume
    

    def _get_order_depth(self):
        """
        Gets the order depth for the product from the trading state and extracts the buy and sell orders as dictionaries with price as key and volume as value.
        - Buy orders are sorted in descending order of price (best bid first).
        - Sell orders are sorted in ascending order of price (best ask first).
        """
        order_depth, buy_orders, sell_orders = {}, {}, {}

        try: order_depth: OrderDepth = self.state.order_depths[self.name]
        except: pass
    
        try: buy_orders = {bp: abs(bv) for bp, bv in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
        except: pass
    
        try: sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except: pass

        return buy_orders, sell_orders


    #-------- ORDER HELPERS ---------- #
    def bid(self, price, volume):
        """
        Creates a buy order with the given price and volume, and updates the max allowed buy volume accordingly.
        """
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        order = Order(self.name, int(price), abs_volume)

        self.max_allowed_buy_volume -= abs_volume
        self.orders.append(order)


    def ask(self, price, volume):
        """
        Creates a sell order with the given price and volume, and updates the max allowed sell volume accordingly.
        """
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        order = Order(self.name, int(price), -abs_volume)

        self.max_allowed_sell_volume -= abs_volume
        self.orders.append(order)


    def get_orders(self):
        """
        Must be overridden by each product-specific trader.
        """
        return {}
    


class StaticTrader(ProductTrader):
    """
    Basic market maker for the INTARIAN_PEPPER_ROOT product.
    
    Behavior:
    - Takes cheap asks (below mid-wall) and rich bids (above mid-wall)
    - Posts quotes near the walls with mild overbid/underbid logic
    - Applies a 1-tick inventory-aware skew
    - Applies a soft volume brake based on current inventory
    """
    def __init__(self, state, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, new_trader_data)

    def get_orders(self):

        if self.wall_mid is not None:

            #-------- TAKING LOGIC ---------- #
            MAX_INV_FOR_AGGRESSIVE_TAKING = 30
            
            # Buy cheap asks
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= self.wall_mid - 1:
                    if self.initial_position < MAX_INV_FOR_AGGRESSIVE_TAKING:
                        self.bid(sp, sv)
                
                elif sp <= self.wall_mid and self.initial_position < 0:
                    volume = min(sv, abs(self.initial_position))
                    self.bid(sp, volume)

            # Sell rich bids
            for bp, bv in self.mkt_buy_orders.items():
                if bp >= self.wall_mid + 1:
                    if self.initial_position > -MAX_INV_FOR_AGGRESSIVE_TAKING:
                        self.ask(bp, bv)
                
                elif bp >= self.wall_mid and self.initial_position > 0:
                    volume = min(bv, self.initial_position)
                    self.ask(bp, volume)

            #-------- MAKING LOGIC ---------- #
            bid_price = int(self.bid_wall + 1)
            ask_price = int(self.ask_wall - 1)

            # Overbid best bid under mid‑wall
            for bp, bv in self.mkt_buy_orders.items():
                overbidding_price = bp + 1
                if bv > 1 and overbidding_price < self.wall_mid:
                    bid_price = max(bid_price, overbidding_price)
                    break

                elif bp < self.wall_mid:
                    bid_price = max(bid_price, bp)
                    break

            # Underbid best ask above mid‑wall
            for sp, sv in self.mkt_sell_orders.items():
                underbidding_price = sp - 1
                if sv > 1 and underbidding_price > self.wall_mid:
                    ask_price = min(ask_price, underbidding_price)
                    break

                elif sp > self.wall_mid:
                    ask_price = min(ask_price, sp)
                    break

            #-------- INVENTORY-AWARE 1 TICK SKEW ---------- #
            if self.initial_position < 0:
                bid_price += 1 # short -> improve bid to buy back faster
            
            elif self.initial_position > 0:
                ask_price -= 1 # long -> improve ask to sell down faster


            #-------- SOFT VOLUME BRAKE ---------- #
            if abs(self.initial_position) <= 20:
                volume_scale = 1.0 # full size when mostly flat

            elif abs(self.initial_position) <= 40:
                volume_scale = 0.7 # moderate brake

            else:
                volume_scale = 0.4 # strong brake when really offside

            buy_volume = int(self.max_allowed_buy_volume * volume_scale)
            sell_volume = int(self.max_allowed_sell_volume * volume_scale)

            #-------- POST ORDERS ---------- #
            self.bid(bid_price, buy_volume)
            self.ask(ask_price, sell_volume)

        return {self.name: self.orders}



class DynamicTrader(ProductTrader):
    """
    Fair-value-tilted market maker for the ASH_COATED_OSMIUM product.

    Behavior:
    - Computes an EWMA fair value (alpha = 0.05)
    - Quotes inside the spread (best_bid+1, best_ask-1)
    - Applies a 1-tick bias toward the fair value
    - Scales volume smoothly based on inventory ratio
    """
    def __init__(self, state, new_trader_data):
        super().__init__(DYNAMIC_SYMBOL, state, new_trader_data)

        #-------- EWMA FAIR VALUE ---------- #
        alpha = 0.05
        last_fv = self.last_traderData.get("osmium_fv", self.wall_mid)

        if self.wall_mid is not None and last_fv is not None:
            self.fair_value = alpha * self.wall_mid + (1 - alpha) * last_fv

        else:
            self.fair_value = self.wall_mid

        self.new_trader_data["osmium_fv"] = self.fair_value


    def get_orders(self):

        if self.wall_mid is not None: # is this needed?

            #-------- BASE QUOTES ---------- #
            bid_price = self.best_bid + 1
            ask_price = self.best_ask - 1

            #-------- FAIR VALUE BIAS (1 TICK) ---------- #
            if self.wall_mid < self.fair_value:
                bid_price += 1 # buy slightly more aggressively
                
            elif self.wall_mid > self.fair_value:
                ask_price -= 1 # sell slightly more aggressively

            #-------- INVENTORY-BASED VOLUME SCALING ---------- #
            inv_ratio = abs(self.initial_position) / self.position_limit
            volume_scale = max(0.3, 1 - 0.7 * inv_ratio) # When inv ~ 0  -> scale ~ 1.0; When inv ~ 80 -> scale ~ 0.3

            bid_volume = int(self.max_allowed_buy_volume * volume_scale)
            ask_volume = int(self.max_allowed_sell_volume * volume_scale)

            #-------- POST ORDERS ---------- #
            self.bid(bid_price, bid_volume)
            self.ask(ask_price, ask_volume)
        
        return {self.name: self.orders}



class Trader:
    """
    Main trader class called by the exchange. Routes to product-specific traders and manages traderData.
    """
    def run(self, state: TradingState):
        result:dict[str,list[Order]] = {}
        new_trader_data = {}
        conversions = 0

        product_traders = {
            STATIC_SYMBOL: StaticTrader,
            DYNAMIC_SYMBOL: DynamicTrader
        }

        for symbol, product_trader in product_traders.items():
            if symbol in state.order_depths:
                try:
                    trader = product_trader(state, new_trader_data)
                    result.update(trader.get_orders())     
                except: pass

        try: final_trader_data = json.dumps(new_trader_data)
        except: final_trader_data = ""
    
        return result, conversions, final_trader_data