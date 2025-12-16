#!/usr/bin/env python3
"""
Migration script to populate date fields in existing database records.
Run this once after updating the database models.
"""

import os
import sys
from datetime import datetime as dt
from dotenv import load_dotenv

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from app import app, db, BookingRequest, PreBooking, PendingAgreement, SignedAgreement

def migrate_dates():
    """Migrate existing records to populate date fields."""
    with app.app_context():
        print("Starting date migration...")
        
        # Migrate BookingRequest records
        booking_requests = BookingRequest.query.filter(BookingRequest.check_in_date.is_(None)).all()
        for req in booking_requests:
            try:
                # Assuming the old check_in_date was stored as string
                if hasattr(req, 'check_in_date') and isinstance(req.check_in_date, str):
                    req.check_in_date = dt.strptime(req.check_in_date, '%Y-%m-%d').date()
                if hasattr(req, 'check_out_date') and isinstance(req.check_out_date, str):
                    req.check_out_date = dt.strptime(req.check_out_date, '%Y-%m-%d').date()
            except (ValueError, AttributeError) as e:
                print(f"Error migrating BookingRequest {req.id}: {e}")
        
        # Migrate PreBooking records
        pre_bookings = PreBooking.query.filter(PreBooking.check_in_date.is_(None)).all()
        for pre in pre_bookings:
            try:
                data = pre.data or {}
                if 'check_in_date' in data:
                    pre.check_in_date = dt.strptime(data['check_in_date'], '%Y-%m-%d').date()
                if 'check_out_date' in data:
                    pre.check_out_date = dt.strptime(data['check_out_date'], '%Y-%m-%d').date()
            except (ValueError, KeyError) as e:
                print(f"Error migrating PreBooking {pre.token}: {e}")
        
        # Migrate PendingAgreement records
        pending_agreements = PendingAgreement.query.filter(PendingAgreement.check_in_date.is_(None)).all()
        for pend in pending_agreements:
            try:
                data = pend.data or {}
                if 'check_in_date' in data:
                    pend.check_in_date = dt.strptime(data['check_in_date'], '%Y-%m-%d').date()
                if 'check_out_date' in data:
                    pend.check_out_date = dt.strptime(data['check_out_date'], '%Y-%m-%d').date()
            except (ValueError, KeyError) as e:
                print(f"Error migrating PendingAgreement {pend.id}: {e}")
        
        # SignedAgreement records will need manual review since they don't have date info
        print("Note: SignedAgreement records need manual date assignment")
        
        db.session.commit()
        print("Date migration completed successfully!")

if __name__ == "__main__":
    migrate_dates()