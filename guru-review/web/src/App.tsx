import { Routes, Route } from 'react-router-dom';
import { HeaderBar } from './components/HeaderBar';
import { Deck } from './screens/Deck';
import { EdgeDeck } from './screens/EdgeDeck';
import { Queue } from './screens/Queue';
import { Settings } from './screens/Settings';
import { ApplyResult } from './screens/ApplyResult';
import { Filter } from './screens/Filter';
import { EdgeFilter } from './screens/EdgeFilter';

export function App(): React.ReactElement {
  return (
    <div className="min-h-screen bg-black text-zinc-100">
      <HeaderBar />
      <main className="pb-24">
        <Routes>
          <Route path="/" element={<Deck />} />
          <Route path="/edges" element={<EdgeDeck />} />
          <Route path="/edges/filter" element={<EdgeFilter />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/applied" element={<ApplyResult />} />
          <Route path="/filter" element={<Filter />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
