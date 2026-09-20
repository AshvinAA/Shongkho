import { Component } from 'react'

/**
 * Catches render-time errors in the page tree and shows a recoverable
 * screen instead of a blank app. Wrap around routed content.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Unhandled UI error:', error, info)
  }

  handleReload = () => {
    this.setState({ error: null })
    window.location.assign('/')
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          <h1>Something went wrong</h1>
          <p className="muted">{this.state.error.message || 'Unexpected error'}</p>
          <button type="button" className="btn" onClick={this.handleReload}>
            Go to Dashboard
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
