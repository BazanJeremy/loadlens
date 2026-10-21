// loadlens: the three journeys of the system under test, one DevWeb transaction each.
// Each iteration runs all three once. A transaction passes only on the status code the API
// returns on success; any other code, or a transport error, fails it, and the iteration goes on
// with the next journey. Ranges are the seed's (sut/payments_api/seed_data.py), the same as in
// load/jmeter/loadlens.jmx.

const BASE_URL = "http://127.0.0.1:8000";
const SEEDED_PAYMENTS = 100000;
const FUNDED_ACCOUNTS = 999;
const MERCHANTS = 5000;

function randomId(max) {
    return Math.floor(Math.random() * max) + 1;
}

function journey(name, expectedStatus, request) {
    const transaction = new load.Transaction(name);
    transaction.start();
    let status = null;
    try {
        const response = new load.WebRequest(Object.assign({
            returnBody: false,
            // Returning false keeps the iteration going: the status check below decides.
            handleHTTPError: function () { return false; }
        }, request)).sendSync();
        status = response.status;
    } catch (error) {
        load.log(`${name}: ${error}`, load.LogLevel.error);
    }
    transaction.stop(status === expectedStatus
        ? load.TransactionStatus.Passed
        : load.TransactionStatus.Failed);
}

load.initialize(async function () {
});

load.action("Action", async function () {
    journey("create_payment", 201, {
        id: 1,
        method: "POST",
        url: `${BASE_URL}/payments`,
        headers: { "Content-Type": "application/json" },
        body: {
            account_id: randomId(FUNDED_ACCOUNTS),
            merchant_id: randomId(MERCHANTS),
            amount_cents: 100
        }
    });
    journey("get_payment", 200, {
        id: 2,
        method: "GET",
        url: `${BASE_URL}/payments/${randomId(SEEDED_PAYMENTS)}`
    });
    journey("get_statement", 200, {
        id: 3,
        method: "GET",
        url: `${BASE_URL}/accounts/${randomId(FUNDED_ACCOUNTS)}/statement`
    });
});

load.finalize(async function () {
});
