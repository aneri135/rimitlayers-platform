# backend/app/models/sale.py
#
# PURPOSE: Defines the 'sales' table — every order ever made
#
# This is the most important table in the system.
# Every sale from Etsy, eBay, and your website ends up here.
# This table is also what generates your tax report at year end.
#
# DESIGN DECISIONS:
# - platform field lets us filter by Etsy/eBay/website
# - All money stored as Float — simple for this scale
# - buyer details stored directly — no separate customers table
#   (keeping it simple — you don't need CRM features)
# - processed_at tracks when WE recorded it vs when it happened

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from app.models.database import Base


class Sale(Base):
    """
    Represents a single sale/order from any platform.
    
    Table name: sales
    """
    __tablename__ = "sales"

    # --- PRIMARY KEY ---
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # --- ORDER IDENTIFICATION ---
    order_id = Column(String, unique=True, index=True, nullable=False)
    # unique=True prevents duplicate imports — same order never saved twice
    # index=True makes lookups by order_id fast

    platform = Column(String, nullable=False, index=True)
    # Values: 'etsy', 'ebay', 'website'
    # index=True because we filter by platform constantly

    # --- DATES ---
    order_date = Column(DateTime, nullable=False)
    # When the customer placed the order

    processed_at = Column(DateTime, server_default=func.now())
    # When OUR system recorded it — auto-set to current time

    # --- PRODUCT DETAILS ---
    product_name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    # e.g. 'Lithophanes', 'Lanterns', 'Vases'

    quantity = Column(Integer, default=1)

    # --- MONEY (all in USD) ---
    sale_price = Column(Float, nullable=False)
    # What the customer paid (gross)

    platform_fee = Column(Float, default=0.0)
    # Etsy transaction fee, eBay final value fee, Stripe fee etc.
    # Calculated automatically based on platform rules

    shipping_collected = Column(Float, default=0.0)
    # Shipping amount charged to buyer

    net_revenue = Column(Float, nullable=False)
    # sale_price - platform_fee = what you actually keep
    # Calculated before saving

    # --- BUYER DETAILS ---
    buyer_name = Column(String, nullable=True)
    buyer_email = Column(String, nullable=True)

    # --- SHIPPING ADDRESS ---
    shipping_address = Column(Text, nullable=True)
    # Full address as one string for simplicity

    shipping_city    = Column(String, nullable=True)
    shipping_state   = Column(String, nullable=True)
    shipping_country = Column(String, nullable=True)
    shipping_zip     = Column(String, nullable=True)

    # --- STATUS ---
    status = Column(String, default="completed")
    # Values: 'completed', 'refunded', 'cancelled'

    is_refunded = Column(Boolean, default=False)
    refund_amount = Column(Float, default=0.0)

    # --- SOURCE TRACKING ---
    source = Column(String, default="email_parser")
    # How did this record get into our system?
    # Values: 'email_parser', 'csv_import', 'api', 'manual', 'stripe_webhook'

    notes = Column(Text, nullable=True)
    # Any extra notes — e.g. custom order details

    def __repr__(self):
        return (
            f"<Sale #{self.order_id} | {self.platform} | "
            f"{self.product_name} | ${self.sale_price}>"
        )

    @property
    def tax_year(self):
        """Returns the year of the sale — used for tax filtering"""
        return self.order_date.year if self.order_date else None

    def to_dict(self):
        """
        Converts Sale object to dictionary — used by FastAPI to return JSON.
        
        WHY NOT USE SQLALCHEMY DIRECTLY?
        FastAPI needs plain Python dicts or Pydantic models to return JSON.
        SQLAlchemy objects can't be serialised to JSON directly.
        """
        return {
            "id":                 self.id,
            "order_id":           self.order_id,
            "platform":           self.platform,
            "order_date":         self.order_date.isoformat() if self.order_date else None,
            "processed_at":       self.processed_at.isoformat() if self.processed_at else None,
            "product_name":       self.product_name,
            "category":           self.category,
            "quantity":           self.quantity,
            "sale_price":         self.sale_price,
            "platform_fee":       self.platform_fee,
            "shipping_collected": self.shipping_collected,
            "net_revenue":        self.net_revenue,
            "buyer_name":         self.buyer_name,
            "buyer_email":        self.buyer_email,
            "shipping_address":   self.shipping_address,
            "shipping_city":      self.shipping_city,
            "shipping_state":     self.shipping_state,
            "shipping_country":   self.shipping_country,
            "shipping_zip":       self.shipping_zip,
            "status":             self.status,
            "is_refunded":        self.is_refunded,
            "refund_amount":      self.refund_amount,
            "source":             self.source,
            "notes":              self.notes,
        }