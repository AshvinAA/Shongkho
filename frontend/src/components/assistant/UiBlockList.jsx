import SalesTrend from '../analytics/SalesTrend.jsx'
import EmployeeRace from '../analytics/EmployeeRace.jsx'
import TopProducts from '../analytics/TopProducts.jsx'

/**
 * Assistant ui_blocks renderer (Part B, doc §3.5).
 *
 * The BACKEND assembles ui_blocks from raw tool results via a fixed
 * mapping; this component just renders each block by type with the
 * dashboard's existing sections — the assistant reuses exactly the
 * same charts, and the LLM never authors the data.
 *
 * block shapes (from the fixed tool -> component mapping):
 *   sales_chart           -> sales section payload  (SalesTrend)
 *   employee_leaderboard  -> employees lane payload (EmployeeRace)
 *   product_table         -> products payload       (TopProducts)
 */
const RENDERERS = {
  sales_chart: (data) => <SalesTrend data={data} />,
  employee_leaderboard: (data) => <EmployeeRace data={data} />,
  product_table: (data) => <TopProducts data={data} />,
}

export default function UiBlockList({ blocks }) {
  if (!blocks?.length) return null
  return (
    <>
      {blocks.map((block, i) => {
        const render = RENDERERS[block.type]
        if (!render) return null
        return (
          <div className="assistant-block" key={i}>
            {render(block.data)}
          </div>
        )
      })}
    </>
  )
}
