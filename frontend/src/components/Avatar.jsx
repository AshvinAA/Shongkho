/**
 * Avatar with automatic initials fallback.
 *
 *   <Avatar user={{ name, photo }} />        — person avatar (navbar, roster)
 *   <Avatar product={{ product_name, photo }} /> — product picture (grid, POS)
 *
 * Shows the image when a photo URL exists, otherwise the first letter of the
 * name (or a 📦 emoji for products) on a colored circle.
 */
export default function Avatar({ user, product, size = 'md', className = '' }) {
  const name = user?.name || product?.product_name || '?'
  const photo = user?.photo || product?.photo
  const isProduct = !user && !!product

  const initials = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()

  const classes = [
    'avatar',
    isProduct ? 'avatar-product' : 'avatar-person',
    `avatar-${size}`,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  if (photo) {
    return (
      <span className={classes} title={name}>
        <img src={photo} alt={name} className="avatar-img" />
      </span>
    )
  }

  return (
    <span className={classes} title={name} aria-hidden="true">
      {isProduct ? '📦' : initials || '?'}
    </span>
  )
}
