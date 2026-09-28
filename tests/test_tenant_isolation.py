import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_tenant_isolation.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_BILLING_REQUIRED"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as salon


def setup_database():
    salon.app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"],
        SALON_PRO_BILLING_REQUIRED=False,
    )
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()

        owner1 = salon.User(
            username="owner1",
            password_hash=salon.generate_password_hash("password-1"),
            role="admin",
        )
        owner2 = salon.User(
            username="owner2",
            password_hash=salon.generate_password_hash("password-2"),
            role="admin",
        )
        salon.db.session.add_all([owner1, owner2])
        salon.db.session.flush()

        account1 = salon.AccountProfile(
            user_id=owner1.id,
            business_name="Salon One",
        )
        account2 = salon.AccountProfile(
            user_id=owner2.id,
            business_name="Salon Two",
        )
        salon.db.session.add_all([account1, account2])
        salon.db.session.flush()

        customer1 = salon.Customer(
            name="Customer One",
            phone="9000000001",
            account_id=account1.id,
        )
        customer2 = salon.Customer(
            name="Customer Two",
            phone="9000000002",
            account_id=account2.id,
        )
        salon.db.session.add_all([customer1, customer2])
        ids = (owner1.id, owner2.id, customer1.id, customer2.id)
        salon.db.session.commit()
        return ids


def login(client, username, password):
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response


def test_customers_are_isolated_by_salon_account():
    owner1_id, owner2_id, customer1_id, customer2_id = setup_database()

    with salon.app.test_client() as client1:
        login(client1, "owner1", "password-1")

        own = client1.get(f"/customers/{customer1_id}")
        assert own.status_code == 200
        assert b"Customer One" in own.data

        foreign = client1.get(f"/customers/{customer2_id}")
        assert foreign.status_code == 404

        deleted = client1.post(
            f"/customers/delete/{customer2_id}",
            follow_redirects=True,
        )
        assert deleted.status_code == 200

    with salon.app.app_context():
        assert salon.db.session.get(salon.Customer, customer2_id) is not None

    with salon.app.test_client() as client2:
        login(client2, "owner2", "password-2")

        own = client2.get(f"/customers/{customer2_id}")
        assert own.status_code == 200
        assert b"Customer Two" in own.data

        foreign = client2.get(f"/customers/{customer1_id}")
        assert foreign.status_code == 404
