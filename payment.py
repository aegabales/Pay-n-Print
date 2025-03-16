import sys
import random
import time

def process_payment(amount):
    print(f"Processing payment of {amount:.2f} pesos...")
    time.sleep(2)  # Simulate network delay
    
    # Simulating payment success or failure (80% success rate)
    if random.random() < 0.8:
        print("Payment successful!")
        return "success"
    else:
        print("Payment failed!")
        return "failure"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 payment.py <amount>")
        sys.exit(1)
    
    try:
        amount = float(sys.argv[1])
        result = process_payment(amount)
        print(result)  # This is captured by the main Flask app
    except ValueError:
        print("Invalid amount provided.")
        sys.exit(1)
