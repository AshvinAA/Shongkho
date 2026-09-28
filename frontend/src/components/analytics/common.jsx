/**
 * Analytics shared controls — now thin re-exports of the design-system
 * primitives (src/components/ui) so the whole app has ONE SegmentedControl
 * and ONE DeltaChip. Existing imports keep working.
 */
import { SegmentedControl, DeltaChip } from '../ui/index.jsx'

export { SegmentedControl, DeltaChip }
export default { SegmentedControl, DeltaChip }
