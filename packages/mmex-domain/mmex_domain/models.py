"""SQLAlchemy mappings for MMEX `_V1` tables (schema as of database v19–v21)."""

from __future__ import annotations

from sqlalchemy import Integer, Numeric, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "ACCOUNTLIST_V1"

    account_id: Mapped[int] = mapped_column("ACCOUNTID", Integer, primary_key=True)
    account_name: Mapped[str] = mapped_column("ACCOUNTNAME", Text)
    account_type: Mapped[str] = mapped_column("ACCOUNTTYPE", Text)
    account_num: Mapped[str | None] = mapped_column("ACCOUNTNUM", Text)
    status: Mapped[str] = mapped_column("STATUS", Text)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    held_at: Mapped[str | None] = mapped_column("HELDAT", Text)
    website: Mapped[str | None] = mapped_column("WEBSITE", Text)
    contact_info: Mapped[str | None] = mapped_column("CONTACTINFO", Text)
    access_info: Mapped[str | None] = mapped_column("ACCESSINFO", Text)
    initial_bal: Mapped[float | None] = mapped_column("INITIALBAL", Numeric)
    initial_date: Mapped[str | None] = mapped_column("INITIALDATE", Text)
    favorite_acct: Mapped[str] = mapped_column("FAVORITEACCT", Text)
    currency_id: Mapped[int] = mapped_column("CURRENCYID", Integer)
    statement_locked: Mapped[int | None] = mapped_column("STATEMENTLOCKED", Integer)
    statement_date: Mapped[str | None] = mapped_column("STATEMENTDATE", Text)
    minimum_balance: Mapped[float | None] = mapped_column("MINIMUMBALANCE", Numeric)
    credit_limit: Mapped[float | None] = mapped_column("CREDITLIMIT", Numeric)
    interest_rate: Mapped[float | None] = mapped_column("INTERESTRATE", Numeric)
    payment_due_date: Mapped[str | None] = mapped_column("PAYMENTDUEDATE", Text)
    minimum_payment: Mapped[float | None] = mapped_column("MINIMUMPAYMENT", Numeric)


class Asset(Base):
    __tablename__ = "ASSETS_V1"

    asset_id: Mapped[int] = mapped_column("ASSETID", Integer, primary_key=True)
    start_date: Mapped[str] = mapped_column("STARTDATE", Text)
    asset_name: Mapped[str] = mapped_column("ASSETNAME", Text)
    asset_status: Mapped[str | None] = mapped_column("ASSETSTATUS", Text)
    currency_id: Mapped[int | None] = mapped_column("CURRENCYID", Integer)
    value_change_mode: Mapped[str | None] = mapped_column("VALUECHANGEMODE", Text)
    value: Mapped[float | None] = mapped_column("VALUE", Numeric)
    value_change: Mapped[str | None] = mapped_column("VALUECHANGE", Text)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    value_change_rate: Mapped[float | None] = mapped_column("VALUECHANGERATE", Numeric)
    asset_type: Mapped[str | None] = mapped_column("ASSETTYPE", Text)


class BillsDeposit(Base):
    __tablename__ = "BILLSDEPOSITS_V1"

    bd_id: Mapped[int] = mapped_column("BDID", Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column("ACCOUNTID", Integer)
    to_account_id: Mapped[int | None] = mapped_column("TOACCOUNTID", Integer)
    payee_id: Mapped[int] = mapped_column("PAYEEID", Integer)
    trans_code: Mapped[str] = mapped_column("TRANSCODE", Text)
    trans_amount: Mapped[float] = mapped_column("TRANSAMOUNT", Numeric)
    status: Mapped[str | None] = mapped_column("STATUS", Text)
    transaction_number: Mapped[str | None] = mapped_column("TRANSACTIONNUMBER", Text)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    categ_id: Mapped[int | None] = mapped_column("CATEGID", Integer)
    trans_date: Mapped[str | None] = mapped_column("TRANSDATE", Text)
    followup_id: Mapped[int | None] = mapped_column("FOLLOWUPID", Integer)
    to_trans_amount: Mapped[float | None] = mapped_column("TOTRANSAMOUNT", Numeric)
    repeats: Mapped[int | None] = mapped_column("REPEATS", Integer)
    next_occurrence_date: Mapped[str | None] = mapped_column("NEXTOCCURRENCEDATE", Text)
    num_occurrences: Mapped[int | None] = mapped_column("NUMOCCURRENCES", Integer)
    color: Mapped[int | None] = mapped_column("COLOR", Integer)


class BudgetSplit(Base):
    __tablename__ = "BUDGETSPLITTRANSACTIONS_V1"

    split_trans_id: Mapped[int] = mapped_column("SPLITTRANSID", Integer, primary_key=True)
    trans_id: Mapped[int] = mapped_column("TRANSID", Integer)
    categ_id: Mapped[int | None] = mapped_column("CATEGID", Integer)
    split_trans_amount: Mapped[float | None] = mapped_column("SPLITTRANSAMOUNT", Numeric)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)


class BudgetEntry(Base):
    __tablename__ = "BUDGETTABLE_V1"

    budget_entry_id: Mapped[int] = mapped_column("BUDGETENTRYID", Integer, primary_key=True)
    budget_year_id: Mapped[int | None] = mapped_column("BUDGETYEARID", Integer)
    categ_id: Mapped[int | None] = mapped_column("CATEGID", Integer)
    period: Mapped[str] = mapped_column("PERIOD", Text)
    amount: Mapped[float] = mapped_column("AMOUNT", Numeric)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    active: Mapped[int | None] = mapped_column("ACTIVE", Integer)


class BudgetYear(Base):
    __tablename__ = "BUDGETYEAR_V1"

    budget_year_id: Mapped[int] = mapped_column("BUDGETYEARID", Integer, primary_key=True)
    budget_year_name: Mapped[str] = mapped_column("BUDGETYEARNAME", Text)


class Category(Base):
    __tablename__ = "CATEGORY_V1"

    categ_id: Mapped[int] = mapped_column("CATEGID", Integer, primary_key=True)
    categ_name: Mapped[str] = mapped_column("CATEGNAME", Text)
    active: Mapped[int | None] = mapped_column("ACTIVE", Integer)
    parent_id: Mapped[int | None] = mapped_column("PARENTID", Integer)


class Checking(Base):
    __tablename__ = "CHECKINGACCOUNT_V1"

    trans_id: Mapped[int] = mapped_column("TRANSID", Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column("ACCOUNTID", Integer)
    to_account_id: Mapped[int | None] = mapped_column("TOACCOUNTID", Integer)
    payee_id: Mapped[int] = mapped_column("PAYEEID", Integer)
    trans_code: Mapped[str] = mapped_column("TRANSCODE", Text)
    trans_amount: Mapped[float] = mapped_column("TRANSAMOUNT", Numeric)
    status: Mapped[str | None] = mapped_column("STATUS", Text)
    transaction_number: Mapped[str | None] = mapped_column("TRANSACTIONNUMBER", Text)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    categ_id: Mapped[int | None] = mapped_column("CATEGID", Integer)
    trans_date: Mapped[str | None] = mapped_column("TRANSDATE", Text)
    last_updated_time: Mapped[str | None] = mapped_column("LASTUPDATEDTIME", Text)
    deleted_time: Mapped[str | None] = mapped_column("DELETEDTIME", Text)
    followup_id: Mapped[int | None] = mapped_column("FOLLOWUPID", Integer)
    to_trans_amount: Mapped[float | None] = mapped_column("TOTRANSAMOUNT", Numeric)
    color: Mapped[int | None] = mapped_column("COLOR", Integer)


class CurrencyHistory(Base):
    __tablename__ = "CURRENCYHISTORY_V1"

    curr_hist_id: Mapped[int] = mapped_column("CURRHISTID", Integer, primary_key=True)
    currency_id: Mapped[int] = mapped_column("CURRENCYID", Integer)
    curr_date: Mapped[str] = mapped_column("CURRDATE", Text)
    curr_value: Mapped[float] = mapped_column("CURRVALUE", Numeric)
    curr_upd_type: Mapped[int | None] = mapped_column("CURRUPDTYPE", Integer)


class Currency(Base):
    __tablename__ = "CURRENCYFORMATS_V1"

    currency_id: Mapped[int] = mapped_column("CURRENCYID", Integer, primary_key=True)
    currency_name: Mapped[str] = mapped_column("CURRENCYNAME", Text)
    pfx_symbol: Mapped[str | None] = mapped_column("PFX_SYMBOL", Text)
    sfx_symbol: Mapped[str | None] = mapped_column("SFX_SYMBOL", Text)
    decimal_point: Mapped[str | None] = mapped_column("DECIMAL_POINT", Text)
    group_separator: Mapped[str | None] = mapped_column("GROUP_SEPARATOR", Text)
    unit_name: Mapped[str | None] = mapped_column("UNIT_NAME", Text)
    cent_name: Mapped[str | None] = mapped_column("CENT_NAME", Text)
    scale: Mapped[int | None] = mapped_column("SCALE", Integer)
    base_conv_rate: Mapped[float | None] = mapped_column("BASECONVRATE", Numeric)
    currency_symbol: Mapped[str] = mapped_column("CURRENCY_SYMBOL", Text)
    currency_type: Mapped[str] = mapped_column("CURRENCY_TYPE", Text)


class Info(Base):
    __tablename__ = "INFOTABLE_V1"

    info_id: Mapped[int] = mapped_column("INFOID", Integer, primary_key=True)
    info_name: Mapped[str] = mapped_column("INFONAME", Text)
    info_value: Mapped[str] = mapped_column("INFOVALUE", Text)


class Payee(Base):
    __tablename__ = "PAYEE_V1"

    payee_id: Mapped[int] = mapped_column("PAYEEID", Integer, primary_key=True)
    payee_name: Mapped[str] = mapped_column("PAYEENAME", Text)
    categ_id: Mapped[int | None] = mapped_column("CATEGID", Integer)
    number: Mapped[str | None] = mapped_column("NUMBER", Text)
    website: Mapped[str | None] = mapped_column("WEBSITE", Text)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    active: Mapped[int | None] = mapped_column("ACTIVE", Integer)
    pattern: Mapped[str | None] = mapped_column("PATTERN", Text)


class Split(Base):
    __tablename__ = "SPLITTRANSACTIONS_V1"

    split_trans_id: Mapped[int] = mapped_column("SPLITTRANSID", Integer, primary_key=True)
    trans_id: Mapped[int] = mapped_column("TRANSID", Integer)
    categ_id: Mapped[int | None] = mapped_column("CATEGID", Integer)
    split_trans_amount: Mapped[float | None] = mapped_column("SPLITTRANSAMOUNT", Numeric)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)


class Stock(Base):
    __tablename__ = "STOCK_V1"

    stock_id: Mapped[int] = mapped_column("STOCKID", Integer, primary_key=True)
    held_at: Mapped[int | None] = mapped_column("HELDAT", Integer)
    purchase_date: Mapped[str] = mapped_column("PURCHASEDATE", Text)
    stock_name: Mapped[str] = mapped_column("STOCKNAME", Text)
    symbol: Mapped[str | None] = mapped_column("SYMBOL", Text)
    num_shares: Mapped[float | None] = mapped_column("NUMSHARES", Numeric)
    purchase_price: Mapped[float] = mapped_column("PURCHASEPRICE", Numeric)
    notes: Mapped[str | None] = mapped_column("NOTES", Text)
    current_price: Mapped[float] = mapped_column("CURRENTPRICE", Numeric)
    value: Mapped[float | None] = mapped_column("VALUE", Numeric)
    commission: Mapped[float | None] = mapped_column("COMMISSION", Numeric)


class StockHistory(Base):
    __tablename__ = "STOCKHISTORY_V1"

    hist_id: Mapped[int] = mapped_column("HISTID", Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column("SYMBOL", Text)
    date: Mapped[str] = mapped_column("DATE", Text)
    value: Mapped[float] = mapped_column("VALUE", Numeric)
    upd_type: Mapped[int | None] = mapped_column("UPDTYPE", Integer)


class Setting(Base):
    __tablename__ = "SETTING_V1"

    setting_id: Mapped[int] = mapped_column("SETTINGID", Integer, primary_key=True)
    setting_name: Mapped[str] = mapped_column("SETTINGNAME", Text)
    setting_value: Mapped[str | None] = mapped_column("SETTINGVALUE", Text)


class Report(Base):
    __tablename__ = "REPORT_V1"

    report_id: Mapped[int] = mapped_column("REPORTID", Integer, primary_key=True)
    report_name: Mapped[str] = mapped_column("REPORTNAME", Text)
    group_name: Mapped[str | None] = mapped_column("GROUPNAME", Text)
    active: Mapped[int | None] = mapped_column("ACTIVE", Integer)
    sql_content: Mapped[str | None] = mapped_column("SQLCONTENT", Text)
    lua_content: Mapped[str | None] = mapped_column("LUACONTENT", Text)
    template_content: Mapped[str | None] = mapped_column("TEMPLATECONTENT", Text)
    description: Mapped[str | None] = mapped_column("DESCRIPTION", Text)


class Attachment(Base):
    __tablename__ = "ATTACHMENT_V1"

    attachment_id: Mapped[int] = mapped_column("ATTACHMENTID", Integer, primary_key=True)
    ref_type: Mapped[str] = mapped_column("REFTYPE", Text)
    ref_id: Mapped[int] = mapped_column("REFID", Integer)
    description: Mapped[str | None] = mapped_column("DESCRIPTION", Text)
    filename: Mapped[str] = mapped_column("FILENAME", Text)


class Usage(Base):
    __tablename__ = "USAGE_V1"

    usage_id: Mapped[int] = mapped_column("USAGEID", Integer, primary_key=True)
    usage_date: Mapped[str] = mapped_column("USAGEDATE", Text)
    json_content: Mapped[str] = mapped_column("JSONCONTENT", Text)


class CustomField(Base):
    __tablename__ = "CUSTOMFIELD_V1"

    field_id: Mapped[int] = mapped_column("FIELDID", Integer, primary_key=True)
    ref_type: Mapped[str] = mapped_column("REFTYPE", Text)
    description: Mapped[str | None] = mapped_column("DESCRIPTION", Text)
    type: Mapped[str] = mapped_column("TYPE", Text)
    properties: Mapped[str] = mapped_column("PROPERTIES", Text)


class CustomFieldData(Base):
    __tablename__ = "CUSTOMFIELDDATA_V1"

    field_data_id: Mapped[int] = mapped_column("FIELDATADID", Integer, primary_key=True)
    field_id: Mapped[int] = mapped_column("FIELDID", Integer)
    ref_id: Mapped[int] = mapped_column("REFID", Integer)
    content: Mapped[str | None] = mapped_column("CONTENT", Text)


class TransLink(Base):
    __tablename__ = "TRANSLINK_V1"

    translink_id: Mapped[int] = mapped_column("TRANSLINKID", Integer, primary_key=True)
    checking_account_id: Mapped[int] = mapped_column("CHECKINGACCOUNTID", Integer)
    link_type: Mapped[str] = mapped_column("LINKTYPE", Text)
    link_record_id: Mapped[int] = mapped_column("LINKRECORDID", Integer)


class ShareInfo(Base):
    __tablename__ = "SHAREINFO_V1"

    share_info_id: Mapped[int] = mapped_column("SHAREINFOID", Integer, primary_key=True)
    checking_account_id: Mapped[int] = mapped_column("CHECKINGACCOUNTID", Integer)
    share_number: Mapped[float | None] = mapped_column("SHARENUMBER", Numeric)
    share_price: Mapped[float | None] = mapped_column("SHAREPRICE", Numeric)
    share_commission: Mapped[float | None] = mapped_column("SHARECOMMISSION", Numeric)
    share_lot: Mapped[str | None] = mapped_column("SHARELOT", Text)


class Tag(Base):
    __tablename__ = "TAG_V1"

    tag_id: Mapped[int] = mapped_column("TAGID", Integer, primary_key=True)
    tag_name: Mapped[str] = mapped_column("TAGNAME", Text)
    active: Mapped[int | None] = mapped_column("ACTIVE", Integer)


class TagLink(Base):
    __tablename__ = "TAGLINK_V1"

    tag_link_id: Mapped[int] = mapped_column("TAGLINKID", Integer, primary_key=True)
    ref_type: Mapped[str] = mapped_column("REFTYPE", Text)
    ref_id: Mapped[int] = mapped_column("REFID", Integer)
    tag_id: Mapped[int] = mapped_column("TAGID", Integer)


MAPPED_TABLES: tuple[type[Base], ...] = (
    Account,
    Asset,
    BillsDeposit,
    BudgetSplit,
    BudgetEntry,
    BudgetYear,
    Category,
    Checking,
    CurrencyHistory,
    Currency,
    Info,
    Payee,
    Split,
    Stock,
    StockHistory,
    Setting,
    Report,
    Attachment,
    Usage,
    CustomField,
    CustomFieldData,
    TransLink,
    ShareInfo,
    Tag,
    TagLink,
)
