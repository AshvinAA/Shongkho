/**
 * POS page tests: cart mechanics, totals math, and checkout gating.
 *
 * The API layer is mocked (like AuthContext tests); the backend's own
 * checkout math is verified separately by the pytest suite.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock every API module the POS page touches.
vi.mock('../api/products.js', () => ({ listProducts: vi.fn() }))
vi.mock('../api/customers.js', () => ({
  getCustomerByPhone: vi.fn(),
  createCustomer: vi.fn(),
}))
vi.mock('../api/sales.js', () => ({ checkout: vi.fn() }))

import * as productsApi from '../api/products.js'
import * as customersApi from '../api/customers.js'
import * as salesApi from '../api/sales.js'
import POS from '../pages/POS.jsx'

// ---------------------------------------------------------
// Fixture data
// ---------------------------------------------------------
const PRODUCTS = [
  {
    product_id: 1,
    product_name: 'Test Widget',
    category: 'Gadgets',
    retail_price: 60.0,
    cost_price: 40.0,
    stock_quantity: 100,
  },
  {
    product_id: 2,
    product_name: 'Cheap Gadget',
    category: 'Gadgets',
    retail_price: 25.0,
    cost_price: 10.0,
    stock_quantity: 3,
  },
  {
    product_id: 3,
    product_name: 'Sold Out Item',
    category: 'Other',
    retail_price: 15.0,
    cost_price: 8.0,
    stock_quantity: 0,
  },
]

const CUSTOMER = { customer_id: 7, name: 'Walkin Watson', phone_number: '01800000001' }

function renderPOS() {
  return render(<POS />)
}

beforeEach(() => {
  vi.clearAllMocks()
  productsApi.listProducts.mockResolvedValue(PRODUCTS)
})

// ---------------------------------------------------------
// CATALOGUE
// ---------------------------------------------------------
describe('POS catalogue', () => {
  it('renders the product list with prices', async () => {
    renderPOS()
    expect(await screen.findByText('Test Widget')).toBeInTheDocument()
    expect(screen.getByText('Cheap Gadget')).toBeInTheDocument()
    expect(screen.getAllByText('৳60').length).toBeGreaterThan(0)
  })

  it('disables out-of-stock product tiles', async () => {
    renderPOS()
    await screen.findByText('Sold Out Item')
    const tile = screen.getByTitle('Out of stock')
    expect(tile).toBeDisabled()
  })

  it('filters products by search term', async () => {
    const user = userEvent.setup()
    renderPOS()
    await screen.findByText('Test Widget')
    await user.type(screen.getByLabelText(/find product/i), 'cheap')
    expect(screen.queryByText('Test Widget')).not.toBeInTheDocument()
    expect(screen.getByText('Cheap Gadget')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------
// CART MECHANICS
// ---------------------------------------------------------
describe('POS cart mechanics', () => {
  it('adds a product to the cart', async () => {
    const user = userEvent.setup()
    renderPOS()
    await user.click(await screen.findByTitle(/add test widget/i))
    expect(screen.getByText(/current sale \(1 item\)/i)).toBeInTheDocument()
  })

  it('increments quantity when the same product is added again', async () => {
    const user = userEvent.setup()
    renderPOS()
    const tile = await screen.findByTitle(/add test widget/i)
    await user.click(tile)
    await user.click(tile)
    expect(screen.getByText(/current sale \(2 items\)/i)).toBeInTheDocument()
  })

  it('clamps quantity to available stock', async () => {
    const user = userEvent.setup()
    renderPOS()
    // Cheap Gadget has only 3 in stock — four add-clicks must cap at 3.
    const tile = await screen.findByTitle(/add cheap gadget/i)
    await user.click(tile)
    await user.click(tile)
    await user.click(tile)
    await user.click(tile) // would exceed stock
    expect(screen.getByText(/current sale \(3 items\)/i)).toBeInTheDocument()
  })

  it('removes a line when its ✕ button is pressed', async () => {
    const user = userEvent.setup()
    renderPOS()
    await user.click(await screen.findByTitle(/add test widget/i))
    await user.click(screen.getByRole('button', { name: /remove test widget/i }))
    expect(screen.getByText(/cart is empty/i)).toBeInTheDocument()
  })

  it('clears the whole cart', async () => {
    const user = userEvent.setup()
    renderPOS()
    await user.click(await screen.findByTitle(/add test widget/i))
    await user.click(screen.getByRole('button', { name: /clear cart/i }))
    expect(screen.getByText(/cart is empty/i)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------
// TOTALS MATH (floating-point safety)
// ---------------------------------------------------------
describe('POS totals math', () => {
  it('sums line totals exactly — no 0.1+0.2 float dust', async () => {
    const user = userEvent.setup()
    // Prices chosen to trigger IEEE-754 drift: 0.1 + 0.2 = 0.30000000000000004
    productsApi.listProducts.mockResolvedValue([
      { product_id: 11, product_name: 'Dime Item', retail_price: 0.1, stock_quantity: 10 },
      { product_id: 12, product_name: 'Two-Dime Item', retail_price: 0.2, stock_quantity: 10 },
    ])
    renderPOS()
    await user.click(await screen.findByTitle(/add dime item/i))
    await user.click(await screen.findByTitle(/add two-dime item/i))

    // The total must render as ৳0.3, never ৳0.30000000000000004.
    const totalRow = screen.getByText('Total').closest('.summary-row')
    expect(totalRow).toHaveTextContent('৳0.3')
    expect(totalRow.textContent).not.toContain('0.30000000000000004')
  })

  it('shows the running total for multiple quantities', async () => {
    const user = userEvent.setup()
    renderPOS()
    const tile = await screen.findByTitle(/add test widget/i)
    await user.click(tile)
    await user.click(tile) // 2 x 60 = 120
    const totalRow = screen.getByText('Total').closest('.summary-row')
    expect(totalRow).toHaveTextContent('৳120')
  })
})

// ---------------------------------------------------------
// CHECKOUT GATING & FLOW
// ---------------------------------------------------------
describe('POS checkout gating', () => {
  it('disables checkout when the cart is empty', async () => {
    renderPOS()
    await screen.findByText('Test Widget')
    const button = screen.getByRole('button', { name: /complete sale/i })
    expect(button).toBeDisabled()
  })

  it('disables checkout until a customer is selected', async () => {
    const user = userEvent.setup()
    customersApi.getCustomerByPhone.mockResolvedValue(CUSTOMER)
    renderPOS()
    await user.click(await screen.findByTitle(/add test widget/i))
    expect(screen.getByRole('button', { name: /complete sale/i })).toBeDisabled()
  })

  it('completes a sale: correct payload, cart cleared, receipt shown', async () => {
    const user = userEvent.setup()
    customersApi.getCustomerByPhone.mockResolvedValue(CUSTOMER)
    salesApi.checkout.mockResolvedValue({
      transaction_id: 42,
      date: '2026-09-21',
      time: '12:00:00',
      payment_method: 'Cash',
      total_revenue: 120.0,
      items: [{
        product_id: 1, quantity: 2,
        retail_price_at_sale: 60.0, cost_price_at_sale: 40.0,
      }],
    })

    renderPOS()
    await user.click(await screen.findByTitle(/add test widget/i))
    await user.click(await screen.findByTitle(/add test widget/i))

    // Look up the customer (fire blur to trigger the lookup).
    const phone = screen.getByLabelText(/phone number/i)
    await user.type(phone, '01800000001')
    await user.tab() // blur triggers handlePhoneLookup

    const customerCard = await screen.findByText('Walkin Watson')
    expect(customerCard).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /complete sale/i }))

    // The payload sent to the API must contain ids + quantities only.
    await waitFor(() => expect(salesApi.checkout).toHaveBeenCalled())
    const payload = salesApi.checkout.mock.calls[0][0]
    expect(payload).toEqual({
      customer_id: 7,
      payment_method: 'Cash',
      items: [{ product_id: 1, quantity: 2 }],
    })

    // Cart resets and the receipt modal appears.
    expect(await screen.findByText(/sale #42 complete/i)).toBeInTheDocument()
    expect(screen.getByText(/cart is empty/i)).toBeInTheDocument()
  })

  it('keeps the cart and shows the error when checkout fails', async () => {
    const user = userEvent.setup()
    customersApi.getCustomerByPhone.mockResolvedValue(CUSTOMER)
    salesApi.checkout.mockRejectedValue(
      Object.assign(new Error('Not enough stock for "Test Widget"'), { status: 400 }),
    )

    renderPOS()
    await user.click(await screen.findByTitle(/add test widget/i))

    const phone = screen.getByLabelText(/phone number/i)
    await user.type(phone, '01800000001')
    await user.tab()
    await screen.findByText('Walkin Watson')

    await user.click(screen.getByRole('button', { name: /complete sale/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/not enough stock/i)
    // Cart is preserved so the cashier can correct the quantity.
    expect(screen.getByText(/current sale \(1 item\)/i)).toBeInTheDocument()
  })
})
