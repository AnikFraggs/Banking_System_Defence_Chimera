import React, { useState, useEffect, useRef } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
} from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip);

export default function LiveMarketChart() {
  const [algoActive, setAlgoActive] = useState(false);
  const [algoAction, setAlgoAction] = useState('-');
  const [price, setPrice] = useState(26050);
  const [changePercent, setChangePercent] = useState(0);
  const [chartData, setChartData] = useState(Array.from({length: 40}, (_, i) => 26050 + (Math.sin(i/2) * 20)));
  const [labels, setLabels] = useState(Array.from({length: 40}, (_, i) => i));
  useEffect(() => {
    const interval = setInterval(() => {
      const volatility = algoActive ? 15 : 5;
      const change = (Math.random() * volatility) - (volatility/2);
      
      setPrice(prevPrice => {
        const newPrice = prevPrice + change;
        setChangePercent((Math.abs(change) / newPrice) * 100);
        
        setChartData(prevData => {
          const newData = [...prevData.slice(1), newPrice];
          return newData;
        });

        // RL Agent Logic
        if(algoActive && Math.random() > 0.7) {
          if (change < 0) {
            setAlgoAction('BUY (Mean Reversion)');
          } else {
            setAlgoAction('SELL (Take Profit)');
          }
        }

        return newPrice;
      });
    }, 800);

    return () => clearInterval(interval);
  }, [algoActive]);

  const data = {
    labels: labels,
    datasets: [{
      label: 'NIFTY 50',
      data: chartData,
      borderColor: '#00F0FF',
      backgroundColor: 'rgba(0, 240, 255, 0.1)',
      borderWidth: 2,
      fill: true,
      tension: 0.4,
      pointRadius: 0
    }]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { display: false },
      y: { 
        display: true, 
        position: 'right',
        grid: { color: 'rgba(255,255,255,0.05)' },
        ticks: { color: '#888' }
      }
    },
    plugins: { legend: { display: false } }
  };

  const handleTrade = (type) => {
    // You can wire this to your backend later
    console.log(`${type} MARKET - NIFTY26000CE x50 routed via Kafka`);
  };

  return (
    <div className="card mb-6" style={{ background: 'linear-gradient(145deg, rgba(16, 42, 65, 0.9), rgba(10, 29, 45, 0.95))' }}>
      <div className="flex justify-between items-center mb-4">
        <div>
          <p className="eyebrow">LIVE ALGO TRADING TERMINAL</p>
          <h3 className="text-xl font-bold text-white">
            {price.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
            <span className={`text-sm ml-2 ${changePercent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {changePercent >= 0 ? '▲' : '▼'} {changePercent.toFixed(3)}%
            </span>
          </h3>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-xs text-gray-500">RL Status</p>
            <p className={`font-mono text-sm ${algoActive ? 'text-[#00F0FF]' : 'text-gray-500'}`}>
              {algoActive ? 'ACTIVE (PPO)' : 'STANDBY'}
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" checked={algoActive} onChange={(e) => setAlgoActive(e.target.checked)} className="sr-only peer" />
            <div className="w-11 h-6 bg-gray-700 rounded-full peer peer-checked:bg-[#00F0FF] transition-colors relative after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-5"></div>
          </label>
        </div>
      </div>

      <div style={{ height: '250px' }}>
        <Line data={data} options={options} />
      </div>

      <div className="grid grid-cols-3 gap-4 mt-4">
        <div className="col-span-1 bg-[#0a1d2d] p-3 rounded-lg border border-[#22465c]">
          <p className="text-xs text-gray-500">Algo Action</p>
          <p className={`font-mono font-bold ${algoAction.includes('BUY') ? 'text-green-400' : algoAction.includes('SELL') ? 'text-red-400' : 'text-gray-400'}`}>
            {algoAction}
          </p>
        </div>
        <div className="col-span-2 flex gap-2">
          <button onClick={() => handleTrade('BUY')} className="flex-1 bg-green-600 hover:bg-green-700 text-white font-bold py-2 rounded transition-colors">BUY</button>
          <button onClick={() => handleTrade('SELL')} className="flex-1 bg-red-600 hover:bg-red-700 text-white font-bold py-2 rounded transition-colors">SELL</button>
        </div>
      </div>
    </div>
  );
}