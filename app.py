    return render_template('appointment_form.html', appointment=appt,
                           customers=customers, staff_list=staff_list, services=services)

@app.route('/appointments/status/<int:id>/<status>', methods=['POST'])
@login_required
def update_appointment_status(id, status):
    appt = Appointment.query.get_or_404(id)
    appt.status = status
    # Keep status change and automatic invoice creation in one database transaction.
    # A failure must not leave a completed appointment without its invoice.
    try:
        # Auto-create invoice when completed
        if status == 'Completed':
            existing = Invoice.query.filter_by(appointment_id=appt.id).first()
            if not existing:
                service = Service.query.get(appt.service_id)
                inv = Invoice(
                    appointment_id=appt.id,
                    customer_id=appt.customer_id,
                    amount=service.price,
                    discount=0,
                    tax=round(service.price * get_tax_rate() / 100, 2),
                    total=round(service.price * (1 + get_tax_rate() / 100), 2),
                    payment_status='Pending'
                )
                db.session.add(inv)
                db.session.flush()
                db.session.add(InvoiceItem(invoice_id=inv.id, description=service.name,
                                           quantity=1, unit_price=service.price,
                                           total=service.price))
                flash(f'Appointment marked as Completed. Invoice created (₹{inv.total}).', 'success')
            else:
                flash('Status updated.', 'success')
        else:
            flash('Status updated.', 'success')
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Could not update appointment status. No changes were saved.', 'danger')
    return redirect(url_for('appointments'))

# ==================== INVOICES / BILLING ====================