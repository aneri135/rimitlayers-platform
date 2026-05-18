# backend/app/models/message.py
# Stores all buyer messages from Etsy and eBay

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from app.models.database import Base


class Message(Base):
    __tablename__ = "messages"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    message_id   = Column(String, unique=True, index=True)
    # Unique ID prevents saving same message twice

    platform     = Column(String, nullable=False, index=True)
    # 'etsy' or 'ebay'

    buyer_name   = Column(String, nullable=True)
    buyer_email  = Column(String, nullable=True)
    subject      = Column(String, nullable=True)
    preview      = Column(Text, nullable=True)
    # First 200 chars of message — shown in dashboard

    full_body    = Column(Text, nullable=True)
    # Full message text — used by AI for reply drafting

    received_at  = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, server_default=func.now())

    is_read      = Column(Boolean, default=False)
    is_replied   = Column(Boolean, default=False)

    ai_draft_reply = Column(Text, nullable=True)
    # AI-generated suggested reply — filled when AI feature runs

    order_id     = Column(String, nullable=True)
    # If message is about a specific order, link it

    def to_dict(self):
        return {
            "id":             self.id,
            "message_id":     self.message_id,
            "platform":       self.platform,
            "buyer_name":     self.buyer_name,
            "buyer_email":    self.buyer_email,
            "subject":        self.subject,
            "preview":        self.preview,
            "received_at":    self.received_at.isoformat() if self.received_at else None,
            "is_read":        self.is_read,
            "is_replied":     self.is_replied,
            "ai_draft_reply": self.ai_draft_reply,
            "order_id":       self.order_id,
        }