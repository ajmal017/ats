from ibapi.wrapper import EWrapper
from ibapi.client import EClient
from ibapi.common import *
from ibapi.utils import *
from ibapi.contract import (Contract, ContractDetails)
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.execution import Execution
from ibapi.ticktype import *
from ibapi.commission_report import CommissionReport

from .assets import *
from .orders import *
from .barutils import *
from .requests.request import Request
from .requests.requestmgr import RequestManager

from threading import Thread, Event
import logging
import argparse

import os
import time

import pickle

bars = 0

def to_ib_timestr(dt):
    return dt.strftime("%Y%m%d %H:%M:%S")

def to_duration(dt_start, dt_end):
    return f"{(dt_end - dt_start).seconds} S"

class BrokerPlatform(EWrapper):
    def __init__(self, port, client_id):
        self.client = EClient(wrapper=self)
        EWrapper.__init__(self)

        self.client_id = client_id
        self.port = port

        self.request_manager = RequestManager()
        self.order_manager = OrderManager()

    def error(self, reqId: int, errorCode: int, errorString: str):
        if (reqId):
            self.request_manager.get(reqId).on_error(errorCode, errorString)
            return

        if (errorCode == 2104 or errorCode == 2106):
            print(errorString)
        else:
            super().error(reqId, errorCode, errorString)
            print(errorCode, errorString)

    def winError(self, text: str, lastError: int):
        super().winError(text, lastError)
        print ("winError", text, lastError)

    def connect(self, host="127.0.0.1"):
        self.client.connect(host, self.port, self.client_id)
        self.thread = Thread(target=self.client.run)
        self.thread.start()
        self.connect_event = Event()
        self.connect_event.wait()

    def connectAck(self):
        print("Connected!")

    # Until we get this notification we aren't really ready to run
    # the rest of the system live.
    def nextValidId(self, orderId: int):
        print("Next valid order id", orderId)
        self.order_manager.next_valid_order_id = orderId       
        # Now we are ready and really connected.
        self.connect_event.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        this.request_manager.get(reqId).on_data(locals())

    def contractDetailsEnd(self, reqId: int):
        self.request_manager.mark_finished(reqId)

    def tickPrice(self, reqId: int, tickType: int, price: float,
                  attrib: TickAttrib):
        print(reqId, tickType, price, attrib)

    # def register_request(obj):
    #     reqId = self.request_manager.get_next_free_id(single_use = True)
    #     self.requests[reqId] = obj
    #     return reqId

    # def request_result(reqId, *args):
    #     callback = self.requests.get(reqId, None)
    #     if (callback):
    #         callback.on_response(reqId, *args)
    #         self.request_manager.free_request(reqId)

    # def queue_request(self, request):
    #     req_id = request.id
    #     if (req_id == None):
    #         # historical requests are in the 400 - 500 range
    #         req_id = self.historical_request_next_id
    #         self.historical_request_next_id += 1
    #         request.id = req_id
            
    #     self.historical_requests[req_id] = request

    #     self.request_event = Event()
    #     self.reqHistoricalData(req_id, Stock(request.symbol), to_ib_timestr(request.end), request.duration, request.bar_size, "TRADES", 1, 2, False, ["XYZ"])
    #     self.request_event.wait()

    def handle_request(self, request:Request):
        # Assign a request id
        self.request_manager.add(request)

        # Process it based on type, making appropriate calls into the client.
        request_type = type(request)
        if (request_type == HistoricalDataRequest):
            self.client.reqHistoricalData(request.request_id, request.contract, to_ib_timestr(request.end), request.duration, request.bar_size, "TRADES", 1, 2, False, [])
        elif (request_type == ContractDetailsRequest):
            self.client.reqContractDetails(reqeust.request_id, request.contract)

        # If synchrononous wait on it.
        if (request.is_synchronous):
            request.event.wait()

    def historicalData(self, reqId, bar):
        self.request_manager.get(reqId).on_data(locals())

    def historicalDataEnd(self, reqId:int, start:str, end:str):
        self.request_manager.mark_finished(reqId, locals())

    def reqRealTimeBars(self, reqId, contract, barSize:int,
                        whatToShow:str, useRTH:bool,
                        realTimeBarsOptions):
        self.bar_series_builder[reqId] = barutils.BarAggregator(contract, self.data_dir)
        super().reqRealTimeBars(reqId, contract, barSize, whatToShow, useRTH, realTimeBarsOptions)
        
    def realtimeBar(self, reqId: int, timeStamp: int, open: float, high: float,
                    low: float, close: float, volume: int, wap: float,
                    count: int):
        global bars
        bars += 1
        super().realtimeBar(reqId, timeStamp, open, high, low, close, volume, wap, count)

        b = BarData()
        b.open = open
        b.high = high
        b.time = timeStamp
        b.low = low
        b.close = close
        b.volume = volume
        b.average = wap
        b.barCount = count

        self.bar_series_builder[reqId].add_bar(b)
        local_time = time.localtime(timeStamp)
        pretty_print_time = time.strftime('%Y-%m-%d %H:%M:%S', local_time)
        print(reqId, pretty_print_time, high, low, open, close,
              volume, count)
        pass

    def marketDataType(self, reqId:TickerId, marketDataType:int):
        """TWS sends a marketDataType(type) callback to the API, where
        type is set to Frozen or RealTime, to announce that market data has been
        switched between frozen and real-time. This notification occurs only
        when market data switches between real-time and frozen. The
        marketDataType( ) callback accepts a reqId parameter and is sent per
        every subscription because different contracts can generally trade on a
        different schedule."""
        self.request_manager.get(reqId).on_data(locals())


    def tickPrice(self, reqId:TickerId , tickType:TickType, price:float,
                  attrib:TickAttrib):
        """Market data tick price callback. Handles all price related ticks."""
        self.request_manager.get(reqId).on_data(locals())


    def tickSize(self, reqId:TickerId, tickType:TickType, size:int):
        """Market data tick size callback. Handles all size-related ticks."""
        self.request_manager.get(reqId).on_data(locals())


    def tickSnapshotEnd(self, reqId:int):
        self.request_manager.mark_finished(reqId)

    def tickGeneric(self, reqId:TickerId, tickType:TickType, value:float):
        self.request_manager.get(reqId).on_data(locals())

    def tickString(self, reqId:TickerId, tickType:TickType, value:str):
        self.request_manager.get(reqId).on_data(locals())

    def tickEFP(self, reqId:TickerId, tickType:TickType, basisPoints:float,
                formattedBasisPoints:str, totalDividends:float,
                holdDays:int, futureLastTradeDate:str, dividendImpact:float,
                dividendsToLastTradeDate:float):
        self.request_manager.get(reqId).on_data(locals())

    def orderStatus(self, orderId:OrderId , status:str, filled:float,
                    remaining:float, avgFillPrice:float, permId:int,
                    parentId:int, lastFillPrice:float, clientId:int,
                    whyHeld:str, mktCapPrice: float):
        """This event is called whenever the status of an order changes. It is
        also fired after reconnecting to TWS if the client has any open orders.

        orderId: OrderId - The order ID that was specified previously in the
            call to placeOrder()
        status:str - The order status. Possible values include:
            PendingSubmit - indicates that you have transmitted the order, but have not  yet received confirmation that it has been accepted by the order destination. NOTE: This order status is not sent by TWS and should be explicitly set by the API developer when an order is submitted.
            PendingCancel - indicates that you have sent a request to cancel the order but have not yet received cancel confirmation from the order destination. At this point, your order is not confirmed canceled. You may still receive an execution while your cancellation request is pending. NOTE: This order status is not sent by TWS and should be explicitly set by the API developer when an order is canceled.
            PreSubmitted - indicates that a simulated order type has been accepted by the IB system and that this order has yet to be elected. The order is held in the IB system until the election criteria are met. At that time the order is transmitted to the order destination as specified.
            Submitted - indicates that your order has been accepted at the order destination and is working.
            Cancelled - indicates that the balance of your order has been confirmed canceled by the IB system. This could occur unexpectedly when IB or the destination has rejected your order.
            Filled - indicates that the order has been completely filled.
            Inactive - indicates that the order has been accepted by the system (simulated orders) or an exchange (native orders) but that currently the order is inactive due to system, exchange or other issues.
        filled:int - Specifies the number of shares that have been executed.
            For more information about partial fills, see Order Status for Partial Fills.
        remaining:int -   Specifies the number of shares still outstanding.
        avgFillPrice:float - The average price of the shares that have been executed. This parameter is valid only if the filled parameter value is greater than zero. Otherwise, the price parameter will be zero.
        permId:int -  The TWS id used to identify orders. Remains the same over TWS sessions.
        parentId:int - The order ID of the parent order, used for bracket and auto trailing stop orders.
        lastFilledPrice:float - The last price of the shares that have been executed. This parameter is valid only if the filled parameter value is greater than zero. Otherwise, the price parameter will be zero.
        clientId:int - The ID of the client (or TWS) that placed the order. Note that TWS orders have a fixed clientId and orderId of 0 that distinguishes them from API orders.
        whyHeld:str - This field is used to identify an order held when TWS is trying to locate shares for a short sell. The value used to indicate this is 'locate'.

        """
        self.order_manager.on_order_status(locals())


    def openOrder(self, orderId:OrderId, contract:Contract, order:Order,
                  orderState:OrderState):
        """This function is called to feed in open orders.

        orderID: OrderId - The order ID assigned by TWS. Use to cancel or
            update TWS order.
        contract: Contract - The Contract class attributes describe the contract.
        order: Order - The Order class gives the details of the open order.
        orderState: OrderState - The orderState class includes attributes Used
            for both pre and post trade margin and commission data."""
        self.order_manager.on_open_order(locals())


    def openOrderEnd(self):
        """This is called at the end of a given request for open orders."""
        self.order_manager.on_open_order_end()


    def connectionClosed(self):
        """This function is called when TWS closes the sockets
        connection with the ActiveX control, or when TWS is shut down."""
        self.logAnswer(current_fn_name(), vars())


    def updateAccountValue(self, key:str, val:str, currency:str,
                            accountName:str):
        """ This function is called only when ReqAccountUpdates on
        EEClientSocket object has been called. """

        self.logAnswer(current_fn_name(), vars())


    def updatePortfolio(self, contract:Contract, position:float,
                        marketPrice:float, marketValue:float,
                        averageCost:float, unrealizedPNL:float,
                        realizedPNL:float, accountName:str):
        """This function is called only when reqAccountUpdates on
        EEClientSocket object has been called."""

        self.logAnswer(current_fn_name(), vars())


    def updateAccountTime(self, timeStamp:str):
        self.logAnswer(current_fn_name(), vars())


    def accountDownloadEnd(self, accountName:str):
        """This is called after a batch updateAccountValue() and
        updatePortfolio() is sent."""

        self.logAnswer(current_fn_name(), vars())

    def contractDetails(self, reqId:int, contractDetails:ContractDetails):
        """Receives the full contract's definitons. This method will return all
        contracts matching the requested via EEClientSocket::reqContractDetails.
        For example, one can obtain the whole option chain with it."""

        self.request_manager.get(reqId).on_data(locals())


    def bondContractDetails(self, reqId:int, contractDetails:ContractDetails):
        """This function is called when reqContractDetails function
        has been called for bonds."""

        self.request_manager.get(reqId).on_data(locals())


    def contractDetailsEnd(self, reqId:int):
        """This function is called once all contract details for a given
        request are received. This helps to define the end of an option
        chain."""

        self.logAnswer(current_fn_name(), vars())


    def execDetails(self, reqId:int, contract:Contract, execution:Execution):
        """This event is fired when the reqExecutions() functions is
        invoked, or when an order is filled.  """

        self.request_manager.get(reqId).on_data(locals())


    def execDetailsEnd(self, reqId:int):
        """This function is called once all executions have been sent to
        a client in response to reqExecutions()."""

        self.logAnswer(current_fn_name(), vars())



    def updateMktDepth(self, reqId:TickerId , position:int, operation:int,
                        side:int, price:float, size:int):
        """Returns the order book.

        tickerId -  the request's identifier
        position -  the order book's row being updated
        operation - how to refresh the row:
            0 = insert (insert this new order into the row identified by 'position')
            1 = update (update the existing order in the row identified by 'position')
            2 = delete (delete the existing order at the row identified by 'position').
        side -  0 for ask, 1 for bid
        price - the order's price
        size -  the order's size"""

        self.request_manager.get(reqId).on_data(locals())


    def updateMktDepthL2(self, reqId:TickerId , position:int, marketMaker:str,
                          operation:int, side:int, price:float, size:int):
        """Returns the order book.

        tickerId -  the request's identifier
        position -  the order book's row being updated
        marketMaker - the exchange holding the order
        operation - how to refresh the row:
            0 = insert (insert this new order into the row identified by 'position')
            1 = update (update the existing order in the row identified by 'position')
            2 = delete (delete the existing order at the row identified by 'position').
        side -  0 for ask, 1 for bid
        price - the order's price
        size -  the order's size"""

        self.request_manager.get(reqId).on_data(locals())


    def updateNewsBulletin(self, msgId:int, msgType:int, newsMessage:str,
                           originExch:str):
        """ provides IB's bulletins
        msgId - the bulletin's identifier
        msgType - one of: 1 - Regular news bulletin 2 - Exchange no longer
            available for trading 3 - Exchange is available for trading
        message - the message
        origExchange -    the exchange where the message comes from.  """

        self.request_manager.get(reqId).on_data(locals())


    def managedAccounts(self, accountsList:str):
        """Receives a comma-separated string with the managed account ids."""
        self.logAnswer(current_fn_name(), vars())


    def receiveFA(self, faData:FaDataType , cxml:str):
        """ receives the Financial Advisor's configuration available in the TWS

        faDataType - one of:
            Groups: offer traders a way to create a group of accounts and apply
                 a single allocation method to all accounts in the group.
            Profiles: let you allocate shares on an account-by-account basis
                using a predefined calculation value.
            Account Aliases: let you easily identify the accounts by meaningful
                 names rather than account numbers.
        faXmlData -  the xml-formatted configuration """

        self.logAnswer(current_fn_name(), vars())

    def historicalData(self, reqId: int, bar: BarData):
        """ returns the requested historical data bars

        reqId - the request's identifier
        date  - the bar's date and time (either as a yyyymmss hh:mm:ssformatted
             string or as system time according to the request)
        open  - the bar's open point
        high  - the bar's high point
        low   - the bar's low point
        close - the bar's closing point
        volume - the bar's traded volume if available
        count - the number of trades during the bar's timespan (only available
            for TRADES).
        WAP -   the bar's Weighted Average Price
        hasGaps  -indicates if the data has gaps or not. """

        self.request_manager.get(reqId).on_data(locals())


    def historicalDataEnd(self, reqId:int, start:str, end:str):
        """ Marks the ending of the historical bars reception. """
        self.logAnswer(current_fn_name(), vars())


    def scannerParameters(self, xml:str):
        """ Provides the xml-formatted parameters available to create a market
        scanner.

        xml -   the xml-formatted string with the available parameters."""
        self.logAnswer(current_fn_name(), vars())


    def scannerData(self, reqId:int, rank:int, contractDetails:ContractDetails,
                     distance:str, benchmark:str, projection:str, legsStr:str):
        """ Provides the data resulting from the market scanner request.

        reqid - the request's identifier.
        rank -  the ranking within the response of this bar.
        contractDetails - the data's ContractDetails
        distance -      according to query.
        benchmark -     according to query.
        projection -    according to query.
        legStr - describes the combo legs when the scanner is returning EFP"""

        self.logAnswer(current_fn_name(), vars())


    def scannerDataEnd(self, reqId:int):
        """ Indicates the scanner data reception has terminated.

        reqId - the request's identifier"""

        self.logAnswer(current_fn_name(), vars())


    def realtimeBar(self, reqId: TickerId, time:int, open: float, high: float, low: float, close: float,
                        volume: int, wap: float, count: int):

        """ Updates the real time 5 seconds bars

        reqId - the request's identifier
        bar.time  - start of bar in unix (or 'epoch') time
        bar.endTime - for synthetic bars, the end time (requires TWS v964). Otherwise -1.
        bar.open  - the bar's open value
        bar.high  - the bar's high value
        bar.low   - the bar's low value
        bar.close - the bar's closing value
        bar.volume - the bar's traded volume if available
        bar.WAP   - the bar's Weighted Average Price
        bar.count - the number of trades during the bar's timespan (only available
            for TRADES)."""

        self.request_manager.get(reqId).on_data(locals())


    def currentTime(self, time:int):
        """ Server's current time. This method will receive IB server's system
        time resulting after the invokation of reqCurrentTime. """

        self.logAnswer(current_fn_name(), vars())


    def fundamentalData(self, reqId:TickerId , data:str):
        """This function is called to receive Reuters global fundamental
        market data. There must be a subscription to Reuters Fundamental set
        up in Account Management before you can receive this data."""

        self.request_manager.get(reqId).on_data(locals())


    def deltaNeutralValidation(self, reqId:int, underComp:UnderComp):
        """Upon accepting a Delta-Neutral RFQ(request for quote), the
        server sends a deltaNeutralValidation() message with the UnderComp
        structure. If the delta and price fields are empty in the original
        request, the confirmation will contain the current values from the
        server. These values are locked when the RFQ is processed and remain
        locked until the RFQ is canceled."""

        self.request_manager.get(reqId).on_data(locals())



    def commissionReport(self, commissionReport:CommissionReport):
        """The commissionReport() callback is triggered as follows:
        - immediately after a trade execution
        - by calling reqExecutions()."""

        self.logAnswer(current_fn_name(), vars())


    def position(self, account:str, contract:Contract, position:float,
                 avgCost:float):
        """This event returns real-time positions for all accounts in
        response to the reqPositions() method."""

        self.logAnswer(current_fn_name(), vars())


    def positionEnd(self):
        """This is called once all position data for a given request are
        received and functions as an end marker for the position() data. """

        self.logAnswer(current_fn_name(), vars())


    def accountSummary(self, reqId:int, account:str, tag:str, value:str,
                       currency:str):
        """Returns the data from the TWS Account Window Summary tab in
        response to reqAccountSummary()."""

        self.request_manager.get(reqId).on_data(locals())


    def accountSummaryEnd(self, reqId:int):
        """This method is called once all account summary data for a
        given request are received."""

        self.logAnswer(current_fn_name(), vars())


    def displayGroupList(self, reqId:int, groups:str):
        """This callback is a one-time response to queryDisplayGroups().

        reqId - The requestId specified in queryDisplayGroups().
        groups - A list of integers representing visible group ID separated by
            the | character, and sorted by most used group first. This list will
             not change during TWS session (in other words, user cannot add a
            new group; sorting can change though)."""

        self.request_manager.get(reqId).on_data(locals())


    def displayGroupUpdated(self, reqId:int, contractInfo:str):
        """This is sent by TWS to the API client once after receiving
        the subscription request subscribeToGroupEvents(), and will be sent
        again if the selected contract in the subscribed display group has
        changed.

        requestId - The requestId specified in subscribeToGroupEvents().
        contractInfo - The encoded value that uniquely represents the contract
            in IB. Possible values include:
            none = empty selection
            contractID@exchange = any non-combination contract.
                Examples: 8314@SMART for IBM SMART; 8314@ARCA for IBM @ARCA.
            combo = if any combo is selected.  """

        self.request_manager.get(reqId).on_data(locals())


    def positionMulti(self, reqId:int, account:str, modelCode:str,
                      contract:Contract, pos:float, avgCost:float):
        """same as position() except it can be for a certain
        account/model"""

        self.request_manager.get(reqId).on_data(locals())


    def positionMultiEnd(self, reqId:int):
        """same as positionEnd() except it can be for a certain
        account/model"""

        self.logAnswer(current_fn_name(), vars())


    def accountUpdateMulti(self, reqId:int, account:str, modelCode:str,
                            key:str, value:str, currency:str):
        """same as updateAccountValue() except it can be for a certain
        account/model"""

        self.request_manager.get(reqId).on_data(locals())


    def accountUpdateMultiEnd(self, reqId:int):
        """same as accountDownloadEnd() except it can be for a certain
        account/model"""

        self.logAnswer(current_fn_name(), vars())


    def tickOptionComputation(self, reqId:TickerId, tickType:TickType ,
            impliedVol:float, delta:float, optPrice:float, pvDividend:float,
            gamma:float, vega:float, theta:float, undPrice:float):
        """This function is called when the market in an option or its
        underlier moves. TWS's option model volatilities, prices, and
        deltas, along with the present value of dividends expected on that
        options underlier are received."""

        self.request_manager.get(reqId).on_data(locals())


    def securityDefinitionOptionParameter(self, reqId:int, exchange:str,
        underlyingConId:int, tradingClass:str, multiplier:str,
        expirations:SetOfString, strikes:SetOfFloat):
        """ Returns the option chain for an underlying on an exchange
        specified in reqSecDefOptParams There will be multiple callbacks to
        securityDefinitionOptionParameter if multiple exchanges are specified
        in reqSecDefOptParams

        reqId - ID of the request initiating the callback
        underlyingConId - The conID of the underlying security
        tradingClass -  the option trading class
        multiplier -    the option multiplier
        expirations - a list of the expiries for the options of this underlying
             on this exchange
        strikes - a list of the possible strikes for options of this underlying
             on this exchange """
        self.request_manager.get(reqId).on_data(locals())


    def securityDefinitionOptionParameterEnd(self, reqId:int):
        """ Called when all callbacks to securityDefinitionOptionParameter are
        complete

        reqId - the ID used in the call to securityDefinitionOptionParameter """
        self.logAnswer(current_fn_name(), vars())


    def softDollarTiers(self, reqId:int, tiers:list):
        """ Called when receives Soft Dollar Tier configuration information

        reqId - The request ID used in the call to EEClient::reqSoftDollarTiers
        tiers - Stores a list of SoftDollarTier that contains all Soft Dollar
            Tiers information """
        self.request_manager.get(reqId).on_data(locals())


    def familyCodes(self, familyCodes:ListOfFamilyCode):
        """ returns array of family codes """
        self.logAnswer(current_fn_name(), vars())        

    def symbolSamples(self, reqId:int,
                      contractDescriptions:ListOfContractDescription):
        """ returns array of sample contract descriptions """
        self.logAnswer(current_fn_name(), vars())


    def mktDepthExchanges(self, depthMktDataDescriptions:ListOfDepthExchanges):
        """ returns array of exchanges which return depth to UpdateMktDepthL2"""
        self.logAnswer(current_fn_name(), vars())

    def tickNews(self, tickerId: int, timeStamp:int, providerCode:str, articleId:str, headline:str, extraData:str):
        """ returns news headlines"""
        self.logAnswer(current_fn_name(), vars())

    def smartComponents(self, reqId:int, map:SmartComponentMap):
        """returns exchange component mapping"""
        self.request_manager.get(reqId).on_data(locals())

    def tickReqParams(self, tickerId:int, minTick:float, bboExchange:str, snapshotPermissions:int):
        """returns exchange map of a particular contract"""
        self.request_manager.get(tickerId).on_data(locals())

    def newsProviders(self, newsProviders:ListOfNewsProviders):
        """returns available, subscribed API news providers"""
        self.logAnswer(current_fn_name(), vars())

    def newsArticle(self, requestId:int, articleType:int, articleText:str):
        """returns body of news article"""
        self.request_manager.get(requestId).on_data(locals())

    def historicalNews(self, requestId:int, time:str, providerCode:str, articleId:str, headline:str):
        """returns historical news headlines"""
        self.request_manager.get(requestId).on_data(locals())

    def historicalNewsEnd(self, requestId:int, hasMore:bool):
        """signals end of historical news"""
        self.request_manager.get(requestId).on_data(locals())

    def headTimestamp(self, reqId:int, headTimestamp:str):
        """returns earliest available data of a type of data for a particular contract"""
        self.request_manager.get(reqId).on_data(locals())

    def histogramData(self, reqId:int, items:HistogramData):
        """returns histogram data for a contract"""
        self.request_manager.get(reqId).on_data(locals())

    def historicalDataUpdate(self, reqId: int, bar: BarData):
        """returns updates in real time when keepUpToDate is set to True"""
        self.request_manager.get(reqId).on_data(locals())

    def rerouteMktDataReq(self, reqId: int, conId: int, exchange: str):
        """returns reroute CFD contract information for market data request"""
        self.request_manager.get(reqId).on_data(locals())

    def rerouteMktDepthReq(self, reqId: int, conId: int, exchange: str):
        """returns reroute CFD contract information for market depth request"""
        self.request_manager.get(reqId).on_data(locals())

    def marketRule(self, marketRuleId: int, priceIncrements: ListOfPriceIncrements):
        """returns minimum price increment structure for a particular market rule ID"""
        self.logAnswer(current_fn_name(), vars())

    def pnl(self, reqId: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float):
        """returns the daily PnL for the account"""
        self.request_manager.get(reqId).on_data(locals())

    def pnlSingle(self, reqId: int, pos: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float, value: float):
        """returns the daily PnL for a single position in the account"""
        self.request_manager.get(reqId).on_data(locals())

    def historicalTicks(self, reqId: int, ticks: ListOfHistoricalTick, done: bool):
        """returns historical tick data when whatToShow=MIDPOINT"""
        self.request_manager.get(reqId).on_data(locals())

    def historicalTicksBidAsk(self, reqId: int, ticks: ListOfHistoricalTickBidAsk, done: bool):
        """returns historical tick data when whatToShow=BID_ASK"""
        self.request_manager.get(reqId).on_data(locals())

    def historicalTicksLast(self, reqId: int, ticks: ListOfHistoricalTickLast, done: bool):
        """returns historical tick data when whatToShow=TRADES"""
        self.request_manager.get(reqId).on_data(locals())

    def tickByTickAllLast(self, reqId: int, tickType: int, time: int, price: float,
                          size: int, attribs: TickAttrib, exchange: str,
                          specialConditions: str):
        """returns tick-by-tick data for tickType = "Last" or "AllLast" """
        self.request_manager.get(reqId).on_data(locals())

    def tickByTickBidAsk(self, reqId: int, time: int, bidPrice: float, askPrice: float,
                         bidSize: int, askSize: int, attribs: TickAttrib):
        """returns tick-by-tick data for tickType = "BidAsk" """
        self.request_manager.get(reqId).on_data(locals())

    def tickByTickMidPoint(self, reqId: int, time: int, midPoint: float):
        """returns tick-by-tick data for tickType = "MidPoint" """
        self.request_manager.get(reqId).on_data(locals())