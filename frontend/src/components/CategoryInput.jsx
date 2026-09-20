import { useMemo } from 'react'

/**
 * Text input with a datalist autocomplete for product categories.
 *
 * props:
 *  - value / onChange  controlled input
 *  - suggestions       existing categories to suggest
 *  - id                input + list ids (default "category")
 */
export default function CategoryInput({ value, onChange, suggestions = [], id = 'category', placeholder = 'e.g. Grocery' }) {
  const listId = `${id}-list`

  const options = useMemo(() => {
    const unique = [...new Set(suggestions.filter(Boolean).map((s) => s.trim()))]
    return unique.sort((a, b) => a.localeCompare(b))
  }, [suggestions])

  return (
    <>
      <input
        id={id}
        type="text"
        className="form-control"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
        list={listId}
        autoComplete="off"
      />
      <datalist id={listId}>
        {options.map((opt) => (
          <option key={opt} value={opt} />
        ))}
      </datalist>
    </>
  )
}
