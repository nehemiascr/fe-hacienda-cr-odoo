/****************************************************************************
 *
 *    OpenERP, Open Source Management Solution
 *    Copyright (C) 2016 Aselcis Consulting (http://www.aselcis.com). All Rights Reserved
 *    Copyright (C) 2016 David Gómez Quilón (http://www.aselcis.com). All Rights Reserved
 *
 *    This program is free software: you can redistribute it and/or modify
 *    it under the terms of the GNU Affero General Public License as
 *    published by the Free Software Foundation, either version 3 of the
 *    License, or (at your option) any later version.
 *
 *    This program is distributed in the hope that it will be useful,
 *    but WITHOUT ANY WARRANTY; without even the implied warranty of
 *    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *    GNU Affero General Public License for more details.
 *
 *    You should have received a copy of the GNU Affero General Public License
 *    along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 ******************************************************************************/

odoo.define('cr_pos_electronic_invoice.models', function (require) {
    "use strict";

    var ajax = require('web.ajax');
    var core = require('web.core');
    var models = require('point_of_sale.models');
    var QWeb = core.qweb;
    var _t = core._t;
    var exports = {};

    var _sequence_next = function(seq){
        var idict = {
            'year': moment().format('YYYY'),
            'month': moment().format('MM'),
            'day': moment().format('DD'),
            'y': moment().format('YY'),
            'h12': moment().format('hh')
        };
        var format = function(s, dict){
            s = s || '';
            $.each(dict, function(k, v){
                s = s.replace('%(' + k + ')s', v);
            });
            return s;
        };
        function pad(n, width, z) {
            z = z || '0';
            n = n + '';
            if (n.length < width) {
                n = new Array(width - n.length + 1).join(z) + n;
            }
            return n;
        }
        var num = seq.number_next_actual;
        var prefix = format(seq.prefix, idict);
        var suffix = format(seq.suffix, idict);
        seq.number_next_actual += seq.number_increment;
        //debugger;
        return prefix + pad(num, seq.padding) + suffix;
    };

    var PosModelParent = models.PosModel.prototype;
    models.PosModel = models.PosModel.extend({
        load_server_data: function(){
            console.log('loading server data');
            var self = this;
            // Load POS sequence object
            self.models.push({
                model: 'ir.sequence',
                fields: [],
                ids:    function(self){ return [self.config.sequence_id[0],]; },
                loaded: function(self, sequence){ self.pos_order_sequence = sequence[0]; },
            });
            return PosModelParent.load_server_data.apply(this, arguments);
        },
        formatDate: function(d){
            var month = d.getMonth();
            var day = d.getDate().toString();
            var year = d.getFullYear();
            year = year.toString().substr(-2);
            month = (month + 1).toString();
            if (month.length === 1) {
                month = "0" + month;
            }
            if (day.length === 1){
                day = "0" + day;
            }
            return  day + month + year;
        },
        get_consecutivo: function(order){
            window.obj = this;
            var tipoDeDocumento = '04';
            var numeracion = order.get('sequence_ref');
            numeracion = Array(Math.max(10 - String(numeracion).length + 1, 0)).join(0) + numeracion;
            var sucursal = '001';
            var terminal = '0000' + order.get('terminal');
            var consecutivo = sucursal + terminal + tipoDeDocumento + numeracion;
            return consecutivo;

        },
        get_clave: function (order) {
            var consecutivo = this.get_consecutivo(order);
            var codigoDePais = '506';
            var fecha = this.formatDate(new Date());
            var identificacion = this.company.vat.replace(/\D/g,'');
            identificacion = Array(Math.max(12 - String(identificacion).length + 1, 0)).join(0) + identificacion;
            var situacion = '1';
            var codigoDeSeguridad = '19283746';
            var clave = codigoDePais + fecha + identificacion + consecutivo + situacion + codigoDeSeguridad;
            return clave;

        },
        push_order: function(order, opts) {
            // debugger;
            if (order) {
                // revisar si es normal o devolucion . Pendiente !!!
                order.set({'sequence_ref_number': this.pos_order_sequence.number_next_actual});
                order.set({'sequence_ref': _sequence_next(this.pos_order_sequence)});
                order.set({'terminal':this.pos_order_sequence.code});
                order.set({'number_electronic': this.get_clave(order)});

            };
            console.log('order pushed');
            console.log({order:order});
            // debugger;
            //return PosModelParent.push_order.call(order,opts);
            var orrder = PosModelParent.push_order.apply(this, arguments);
            // orrder['name'] = this.get_consecutivo();
            // orrder['number_electronic'] = this.get_clave();
            console.log({order:orrder});
            return orrder;
        }
    });

    var OrderParent = models.Order.prototype;
    models.Order = models.Order.extend({

        export_for_printing: function(attributes){
            var order = OrderParent.export_for_printing.apply(this, arguments);
            order['sequence_ref'] = this.get('sequence_ref');
            order['sequence_ref_number'] = this.get('sequence_ref_number');
            order['number_electronic'] = this.get('number_electronic');

            console.log('print sequence_ref ' + order['sequence_ref']);
            console.log('print sequence_ref_number ' + order['sequence_ref_number']);
            console.log('print number_electronic ' + order['number_electronic']);
            //debugger;
            return order;
        },
        export_as_JSON: function() {
            var order = OrderParent.export_as_JSON.apply(this, arguments);
            order['sequence_ref'] = this.get('sequence_ref');
            order['sequence_ref_number'] = this.get('sequence_ref_number');
            order['number_electronic'] = this.get('number_electronic');

            console.log('export sequence_ref ' + order['sequence_ref']);
            console.log('export sequence_ref_number ' + order['sequence_ref_number']);
            console.log('export number_electronic ' + order['number_electronic']);
            //debugger;
            return order;
        }
    });

    //models.load_fields('res.company', ['street', 'city', 'state_id', 'zip']);

    return exports;
});