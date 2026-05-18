# backend/app/models/inventory.py
# Tracks stock levels for each product across platforms

from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.models.database import Base


class Inventory(Base):
    __tablename__ = "inventory"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String, nullable=False)
    category     = Column(String, nullable=True)
    platform     = Column(String, nullable=False)
    # 'etsy', 'ebay', 'website'

    stock_qty    = Column(Integer, default=0)
    # Current stock level read from platform

    low_stock_threshold = Column(Integer, default=1)
    # Alert when stock reaches this number

    is_low_stock = Column(Boolean, default=False)
    # True when stock_qty <= low_stock_threshold

    last_synced  = Column(DateTime, server_default=func.now())
    # When we last read this from the platform

    listing_id   = Column(String, nullable=True)
    # Platform's listing ID for reference

    def to_dict(self):
        return {
            "id":           self.id,
            "product_name": self.product_name,
            "category":     self.category,
            "platform":     self.platform,
            "stock_qty":    self.stock_qty,
            "is_low_stock": self.is_low_stock,
            "last_synced":  self.last_synced.isoformat() if self.last_synced else None,
        }