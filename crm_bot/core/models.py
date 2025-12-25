"""ORM-модели упрощённого MVP."""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Базовый класс для ORM."""


class UserRole(str, enum.Enum):
    """Роль пользователя."""

    WORKER = "worker"
    ADMIN = "admin"


class ShiftStatus(str, enum.Enum):
    """Статус смены."""

    OPEN = "open"
    CLOSED = "closed"


class CashTransactionType(str, enum.Enum):
    """Тип операции по балансу смены."""

    OPENING = "OPENING"
    DEAL_ISSUED = "DEAL_ISSUED"
    ADJUSTMENT = "ADJUSTMENT"


class DealPaymentMethod(str, enum.Enum):
    """Способ оплаты операции."""

    CASH = "cash"
    BANK = "bank"


class User(Base):
    """Пользователь (админ или сотрудник)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone = Column(String(32), unique=True, nullable=False)
    name = Column(String(255))
    role = Column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    shifts = relationship("Shift", back_populates="worker")
    deals = relationship("Deal", back_populates="worker")
    transactions = relationship(
        "CashTransaction",
        back_populates="worker",
        foreign_keys="CashTransaction.worker_id",
    )


class Shift(Base):
    """Смена сотрудника и лимит."""

    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True)
    worker_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    opened_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at = Column(DateTime(timezone=True))
    opening_balance_cash = Column(Numeric(12, 2), nullable=False, server_default="0")
    opening_balance_bank = Column(Numeric(12, 2), nullable=False, server_default="0")
    current_balance_cash = Column(Numeric(12, 2), nullable=False, server_default="0")
    current_balance_bank = Column(Numeric(12, 2), nullable=False, server_default="0")
    opening_balance = Column(Numeric(12, 2), nullable=False)
    current_balance = Column(Numeric(12, 2), nullable=False)
    reported_cash = Column(Numeric(12, 2))
    reported_bank = Column(Numeric(12, 2))
    reported_at = Column(DateTime(timezone=True))
    cash_diff = Column(Numeric(12, 2))
    bank_diff = Column(Numeric(12, 2))
    status = Column(
        Enum(
            ShiftStatus,
            name="shift_status",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        server_default=ShiftStatus.OPEN.value,
    )

    worker = relationship("User", back_populates="shifts")
    deals = relationship("Deal", back_populates="shift")
    transactions = relationship("CashTransaction", back_populates="shift")


class DealType(str, enum.Enum):
    """Тип операции."""

    OPERATION = "operation"
    INSTALLMENT = "installment"


class Deal(Base):
    """Операция (выдача/возврат средств)."""

    __tablename__ = "deals"

    id = Column(Integer, primary_key=True)
    worker_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_id = Column(
        Integer,
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_name = Column(String(255), nullable=False)
    client_phone = Column(String(32))
    total_amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(
        Enum(
            DealPaymentMethod,
            name="deal_payment_method",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        server_default=DealPaymentMethod.CASH.value,
    )
    comment = Column(String(255))
    deal_type = Column(
        Enum(
            DealType,
            name="deal_type",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        server_default=DealType.OPERATION.value,
    )
    product_price = Column(Numeric(12, 2))
    markup_percent = Column(Numeric(5, 2))
    markup_amount = Column(Numeric(12, 2))
    installment_term_months = Column(Integer)
    down_payment_amount = Column(Numeric(12, 2))
    installment_total_amount = Column(Numeric(12, 2))
    monthly_payment_amount = Column(Numeric(12, 2))
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    is_deleted = Column(
        Boolean,
        nullable=False,
        server_default="false",
        default=False,
    )

    worker = relationship("User", back_populates="deals")
    shift = relationship("Shift", back_populates="deals")
    transactions = relationship("CashTransaction", back_populates="deal")
    payments = relationship("Payment", back_populates="deal")


class CashTransaction(Base):
    """Леджер операций по смене."""

    __tablename__ = "cash_transactions"

    id = Column(Integer, primary_key=True)
    worker_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_id = Column(
        Integer,
        ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=False,
    )
    deal_id = Column(
        Integer,
        ForeignKey("deals.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    type = Column(
        Enum(
            CashTransactionType,
            name="cash_transaction_type",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
    )
    amount_delta = Column(Numeric(12, 2), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    worker = relationship(
        "User",
        foreign_keys=[worker_id],
        back_populates="transactions",
    )
    shift = relationship("Shift", back_populates="transactions")
    deal = relationship("Deal", back_populates="transactions")
    creator = relationship("User", foreign_keys=[created_by])


class Payment(Base):
    """Факт поступления оплаты по операции (не влияет на лимит)."""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    deal_id = Column(
        Integer,
        ForeignKey("deals.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount = Column(Numeric(12, 2), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    deal = relationship("Deal", back_populates="payments")
