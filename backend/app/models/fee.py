# backend/app/models/fee.py
# Tracks ALL fees paid to platforms — critical for tax filing
#
# WHY A SEPARATE TABLE?
# Fees come in different types at different times:
# - Per-transaction fees (at time of sale)
# - Monthly subscription fees (1st of each month)
# - Listing fees (when listing is created/renewed)
# Keeping them separate makes tax reporting accurate and flexible

from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from app.models.database import Base


class Fee(Base):
    __tablename__ = "fees"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    platform    = Column(String, nullable=False, index=True)
    # 'etsy', 'ebay', 'website', 'stripe', 'twilio'

    fee_type    = Column(String, nullable=False)
    # 'transaction', 'listing', 'subscription', 'processing',
    # 'offsite_ads', 'promoted_listing', 'international', 'domain', 'hosting'

    amount      = Column(Float, nullable=False)
    description = Column(Text, nullable=True)

    fee_date    = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, server_default=func.now())

    order_id    = Column(String, nullable=True)
    # Link to sale if this is a per-transaction fee

    tax_year    = Column(Integer, nullable=True)
    tax_month   = Column(Integer, nullable=True)
    # Pre-calculated for fast tax queries

    def to_dict(self):
        return {
            "id":          self.id,
            "platform":    self.platform,
            "fee_type":    self.fee_type,
            "amount":      self.amount,
            "description": self.description,
            "fee_date":    self.fee_date.isoformat() if self.fee_date else None,
            "order_id":    self.order_id,
            "tax_year":    self.tax_year,
            "tax_month":   self.tax_month,
        }