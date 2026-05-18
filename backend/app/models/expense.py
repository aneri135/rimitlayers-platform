# backend/app/models/expense.py
# Tracks business expenses — materials, shipping supplies, equipment
# These are tax deductible and reduce your taxable income

from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from app.models.database import Base


class Expense(Base):
    __tablename__ = "expenses"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    category     = Column(String, nullable=False)
    # 'materials', 'shipping_supplies', 'equipment', 'software', 'other'

    description  = Column(Text, nullable=False)
    # e.g. "1kg PLA filament - black"

    amount       = Column(Float, nullable=False)
    expense_date = Column(DateTime, nullable=False)
    recorded_at  = Column(DateTime, server_default=func.now())

    vendor       = Column(String, nullable=True)
    # e.g. "Amazon", "Home Depot"

    receipt_ref  = Column(String, nullable=True)
    # Receipt number for your records

    tax_year     = Column(Integer, nullable=True)
    is_deductible = Column(Integer, default=1)
    # 1 = yes, 0 = no

    def to_dict(self):
        return {
            "id":           self.id,
            "category":     self.category,
            "description":  self.description,
            "amount":       self.amount,
            "expense_date": self.expense_date.isoformat() if self.expense_date else None,
            "vendor":       self.vendor,
            "tax_year":     self.tax_year,
            "is_deductible": bool(self.is_deductible),
        }